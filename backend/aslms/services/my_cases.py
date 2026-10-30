"""The caller's own cases (design `portal-ui-redesign`, decisions 5 and 28, API A1 and A2): the Case inbox views
Working on, Files with me, Claimed by me and Disposed, their counts, and the batched row facts (stage, file holder,
allotment, owner) shared with the department's Claimed list (A3).

Working on (design `case-inbox-merge`, decisions 3 and 4) is the active cases allotted to the caller, and every
case whose custody row the caller holds whatever its status; it is ordered by the caller's own due date, then the
next hearing. The `files` view stays for compatibility; the portal no longer reads it.

The portal reads `all` and the `files` count (design `case-inbox-simplify`, decisions 3 and 4): `all` is the three
sets whatever the court status, active cases first, each row with the reasons that put it there (the My Cases
tab); the `files` count is the With Me tab's count and the sidebar pill. The `working`, `claimed` and `disposed`
views stay for compatibility.

Three sets over `cases`, each a condition (correlated `EXISTS`):
- allotted (A): for each active membership with a department, the Claimed-tab rule for the membership itself
  (`visibility.claimed_conditions(..., whole=False)`): the officer is the person, or, for a membership below the
  department, the unit is in its subtree (question 5);
- file (F): the custody row's holder is the person;
- claimed (C): an active primary ownership row of one of the caller's departments whose actor snapshot is the
  person (they claimed it, or accepted the transfer that created it), or whose accepted transfer the person
  decided.

Every view is ANDed with `visibility.visible_case_condition` and excludes merged cases. Reading writes nothing:
no row, no audit, no event."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import ColumnElement, Select, and_, exists, false, or_, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session, aliased

from aslms.core.config import get_settings
from aslms.domain.cases import Case, CaseStatus
from aslms.domain.org import Office, User, UserMembership
from aslms.domain.ownership import (
    CaseOwnership,
    OwnershipRole,
    OwnershipStatus,
    OwnershipTransfer,
    TransferStatus,
)
from aslms.domain.reference import Permission, RefCaseStage, Role, Stage
from aslms.domain.workflow import (
    PENDING_ACTION_LABELS,
    CaseStage,
    Custody,
    CustodyHistory,
    PendingAction,
)
from aslms.services import access, case_filters, inbox, visibility
from aslms.services.case_filters import CaseFilters
from aslms.services.inbox import InboxError, Page
from aslms.services.workflow_common import today_ist

VIEWS = ("working", "files", "all", "claimed", "disposed")
ACTIONS = ("overdue", "due_week")
NO_STAGE = "none"
DUE_WEEK_DAYS = 7

# the custody row read under aliases: the visibility rule's custody basis is a correlated EXISTS over `custody`,
# which must not correlate to this module's own custody subqueries
_FILE = aliased(Custody, name="my_file")
_DUE = aliased(Custody, name="my_due")
_ACT = aliased(Custody, name="act_custody")
_STAGE = aliased(CaseStage, name="latest_stage")


@dataclass
class MyConditions:
    allotted: ColumnElement[bool]
    file: ColumnElement[bool]
    claimed: ColumnElement[bool]


def _or(conds: list[ColumnElement[bool]]) -> ColumnElement[bool]:
    if not conds:
        return false()
    return conds[0] if len(conds) == 1 else or_(*conds)


def my_conditions(session: Session, user: User) -> MyConditions:
    members = [m for m in access.members(session, user) if m.department is not None]
    allotted = _or(
        [
            exists().where(
                CaseOwnership.case_id == Case.id,
                *visibility.claimed_conditions(session, m, m.department, case_state="all", whole=False),
            )
            for m in members
        ]
    )
    file_ = exists().where(_FILE.case_id == Case.id, _FILE.holder_user_id == user.id)
    dept_ids = list({m.department.id for m in members})
    if dept_ids:
        primary_mine = and_(
            CaseOwnership.case_id == Case.id,
            CaseOwnership.role == OwnershipRole.PRIMARY,
            CaseOwnership.status == OwnershipStatus.ACTIVE,
            CaseOwnership.office_id.in_(dept_ids),
        )
        accepted = exists().where(
            OwnershipTransfer.case_id == CaseOwnership.case_id,
            OwnershipTransfer.to_office_id == CaseOwnership.office_id,
            OwnershipTransfer.status == TransferStatus.ACCEPTED,
            OwnershipTransfer.decided_by_user_id == user.id,
        )
        claimed = exists().where(primary_mine, or_(CaseOwnership.actor_user_id == user.id, accepted))
    else:
        claimed = false()
    return MyConditions(allotted=allotted, file=file_, claimed=claimed)


def my_cases_condition(session: Session, user: User) -> ColumnElement[bool]:
    """allotted OR file OR claimed, OR the counsel basis of a standing-counsel membership (the calendar and the
    dashboard, rounds 3 and 4)."""
    c = my_conditions(session, user)
    conds = [c.allotted, c.file, c.claimed]
    for m in access.members(session, user):
        if m.role == Role.STANDING_COUNSEL and m.department is not None:
            conds.append(
                visibility.codes_condition(visibility.counsel_department_codes(session, m.department))
            )
    return or_(*conds)


# ------------------------------------------------------------------------------------------------ filters


def stage_condition(raw: str | None) -> ColumnElement[bool] | None:
    """The case's latest `case_stages` row is `raw` (a `ref_case_stage` code), or `none`: no stage set."""
    if raw is None or str(raw).strip() == "":
        return None
    code = str(raw).strip().lower()
    if code == NO_STAGE:
        return ~exists().where(_STAGE.case_id == Case.id)
    try:
        stage = Stage(code)
    except ValueError as exc:
        raise InboxError(f"unknown stage {raw!r}") from exc
    latest = (
        select(_STAGE.stage)
        .where(_STAGE.case_id == Case.id)
        .order_by(_STAGE.created_at.desc(), _STAGE.id.desc())
        .limit(1)
        .scalar_subquery()
    )
    return latest == stage


def action_condition(
    raw: str | None, *, holder_user_id: uuid.UUID | None = None
) -> ColumnElement[bool] | None:
    """`overdue`: the custody due date is before today (IST) and an action is pending; `due_week`: due today to
    today + 7. With `holder_user_id`, only on that person's file."""
    if raw is None or str(raw).strip() == "":
        return None
    v = str(raw).strip().lower()
    if v not in ACTIONS:
        raise InboxError("action is one of overdue, due_week")
    today = today_ist()
    conds = [_ACT.case_id == Case.id, _ACT.pending_action != PendingAction.NONE, _ACT.due_date.is_not(None)]
    if v == "overdue":
        conds.append(_ACT.due_date < today)
    else:
        conds += [_ACT.due_date >= today, _ACT.due_date <= today + timedelta(days=DUE_WEEK_DAYS)]
    if holder_user_id is not None:
        conds.append(_ACT.holder_user_id == holder_user_id)
    return exists().where(*conds)


def holder_condition(raw: str | None, department: Office) -> ColumnElement[bool] | None:
    """`department`: the file is held inside the department's subtree; `elsewhere`: held outside it. A case with
    no custody row matches neither."""
    if raw is None or str(raw).strip() == "":
        return None
    v = str(raw).strip().lower()
    if v not in ("department", "elsewhere"):
        raise InboxError("holder is one of department, elsewhere")
    inside = _ACT.holder_office_id.in_(visibility.subtree_ids(department))
    return exists().where(_ACT.case_id == Case.id, inside if v == "department" else ~inside)


# ------------------------------------------------------------------------------------------------ the views


def _active() -> ColumnElement[bool]:
    return Case.status.in_([CaseStatus.PENDING, CaseStatus.UNKNOWN])


def _state(view: str) -> ColumnElement[bool] | None:
    """The status rule of a view; Working on carries its own inside `_view_set` (decision 3); `files` and `all`
    have none (design case-inbox-simplify, decision 4)."""
    if view == "claimed":
        return _active()
    if view == "disposed":
        return Case.status == CaseStatus.DISPOSED
    return None


def _view_set(c: MyConditions, view: str) -> ColumnElement[bool]:
    if view == "working":
        # design case-inbox-merge, decision 3: a case with me stays whatever its status
        return or_(and_(c.allotted, _active()), c.file)
    if view == "files":
        return c.file
    if view == "claimed":
        return c.claimed
    # `all` and `disposed`: the three sets (`disposed` adds its status rule in `_state`)
    return or_(c.allotted, c.file, c.claimed)


def mine_stmt(
    session: Session,
    user: User,
    *,
    view: str,
    filters: CaseFilters | None = None,
    stage: str | None = None,
    action: str | None = None,
    conds: MyConditions | None = None,
) -> Select:
    if view not in VIEWS:
        raise InboxError("view is one of working, files, all, claimed, disposed")
    if filters is not None and filters.owner is not None:
        raise InboxError("owner is not a filter of this list")
    c = conds or my_conditions(session, user)
    stmt = select(Case).where(
        Case.merged_into_case_id.is_(None),
        visibility.visible_case_condition(session, user),
        _view_set(c, view),
    )
    state = _state(view)
    if state is not None:
        stmt = stmt.where(state)
    for extra in (stage_condition(stage), action_condition(action, holder_user_id=user.id)):
        if extra is not None:
            stmt = stmt.where(extra)
    return stmt.where(*case_filters.conditions(session, filters))


def _require(session: Session, user: User) -> None:
    access.require(session, user, Permission.CASES_VIEW_SCOPE)


def mine(
    session: Session,
    user: User,
    *,
    view: str,
    filters: CaseFilters | None = None,
    stage: str | None = None,
    action: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> Page:
    """A1: one view of the caller's own cases, each row with its owner, stage, file holder, allotment and the
    reasons (`allotted`, `file`, `claimed`) that put it here."""
    _require(session, user)
    c = my_conditions(session, user)
    stmt = mine_stmt(session, user, view=view, filters=filters, stage=stage, action=action, conds=c)
    limit, offset = inbox.clamp(limit, offset)
    total = inbox._count(session, stmt)
    due = select(_DUE.due_date).where(_DUE.case_id == Case.id).scalar_subquery()
    if view == "files":
        since = select(_DUE.since).where(_DUE.case_id == Case.id).scalar_subquery()
        order = [due.asc().nulls_last(), since, Case.id]
    elif view == "working":
        # design case-inbox-merge, decision 4: my own due date first (overdue first), then the next hearing
        my_due = (
            select(_DUE.due_date)
            .where(
                _DUE.case_id == Case.id,
                _DUE.holder_user_id == user.id,
                _DUE.pending_action != PendingAction.NONE,
            )
            .scalar_subquery()
        )
        order = [
            my_due.asc().nulls_last(),
            Case.next_hearing_on.asc().nulls_last(),
            Case.case_no_text,
            Case.id,
        ]
    else:
        order = [
            Case.next_hearing_on.asc().nulls_last(),
            due.asc().nulls_last(),
            Case.case_no_text,
            Case.id,
        ]
        if view == "all":
            # design case-inbox-simplify, decision 4: active cases first, disposed after them
            order.insert(0, (Case.status == CaseStatus.DISPOSED).asc())
    rows = session.execute(
        stmt.add_columns(c.allotted.label("r_allotted"), c.file.label("r_file"), c.claimed.label("r_claimed"))
        .order_by(*order)
        .limit(limit)
        .offset(offset)
    ).all()
    cases = [r[0] for r in rows]
    summ = inbox.summaries(session, cases)
    briefs = case_briefs(session, user, [x.id for x in cases])
    items = []
    for case, r_allotted, r_file, r_claimed in rows:
        b = briefs.get(case.id, {})
        reasons = [n for n, v in (("allotted", r_allotted), ("file", r_file), ("claimed", r_claimed)) if v]
        items.append(
            {
                "case": summ[case.id],
                "owner_code": b.get("owner_code"),
                "stage": b.get("stage"),
                "custody": b.get("custody"),
                "allotment": b.get("allotment"),
                "reasons": reasons,
            }
        )
    return Page(items, total)


def mine_counts(session: Session, user: User) -> dict[str, int]:
    """A2: the unfiltered totals of the views (`all` added by design case-inbox-simplify, decision 3)."""
    _require(session, user)
    c = my_conditions(session, user)
    return {view: inbox._count(session, mine_stmt(session, user, view=view, conds=c)) for view in VIEWS}


# ------------------------------------------------------------------------------------------------ row facts


def _stage_briefs(session: Session, case_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
    rows = session.execute(
        select(CaseStage.case_id, CaseStage.stage, RefCaseStage.label, RefCaseStage.phase)
        .join(RefCaseStage, RefCaseStage.code == CaseStage.stage)
        .where(CaseStage.case_id.in_(case_ids))
        .ext(distinct_on(CaseStage.case_id))
        .order_by(CaseStage.case_id, CaseStage.created_at.desc(), CaseStage.id.desc())
    ).all()
    return {
        cid: {"stage": Stage(code).value, "label": label, "phase": phase} for cid, code, label, phase in rows
    }


def _custody_briefs(
    session: Session, user: User, case_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[str, Any]]:
    leg = aliased(CustodyHistory, name="brief_leg")
    holder = aliased(User, name="brief_holder")
    rows = session.execute(
        select(
            Custody.case_id,
            Custody.holder_user_id,
            Custody.pending_action,
            Custody.since,
            Custody.due_date,
            Office.code,
            Office.name,
            holder.full_name,
            leg.holder_designation,
            UserMembership.designation,
            leg.actor_name,
            leg.actor_designation,
            leg.actor_office_code,
        )
        .join(Office, Office.id == Custody.holder_office_id)
        .outerjoin(holder, holder.id == Custody.holder_user_id)
        .outerjoin(leg, leg.id == Custody.current_leg_id)
        .outerjoin(UserMembership, UserMembership.id == Custody.holder_membership_id)
        .where(Custody.case_id.in_(case_ids))
    ).all()
    today = today_ist()
    soon_until = today + timedelta(days=get_settings().request_due_soon_days)
    out: dict[uuid.UUID, dict[str, Any]] = {}
    for row in rows:
        cid, holder_id, action, since, due, code, name, full_name, leg_desig, m_desig = row[:10]
        actor_name, actor_desig, actor_office = row[10:]
        act = PendingAction(action)
        overdue = due is not None and due < today and act != PendingAction.NONE
        # design case-inbox-merge, decision 2: the custody card's window (`request_due_soon_days`)
        due_soon = due is not None and not overdue and today <= due <= soon_until
        out[cid] = {
            "holder_office": {"code": code, "name": name},
            "holder_user": (
                {"full_name": full_name, "designation": leg_desig or m_desig}
                if holder_id is not None and full_name is not None
                else None
            ),
            "with_me": holder_id is not None and holder_id == user.id,
            "pending_action": act.value,
            "pending_action_label": PENDING_ACTION_LABELS[act],
            "since": since,
            "due_date": due,
            "overdue": overdue,
            "overdue_days": (today - due).days if overdue else 0,
            "due_soon": due_soon,
            "sent_by": (
                {"name": actor_name, "designation": actor_desig, "office_code": actor_office}
                if actor_name
                else None
            ),
        }
    return out


def _allotments(session: Session, case_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
    unit = aliased(Office, name="allot_unit")
    owner = aliased(Office, name="owner_office")
    officer = aliased(User, name="allot_officer")
    rows = session.execute(
        select(CaseOwnership.case_id, owner.code, unit.code, unit.name, officer.id, officer.full_name)
        .join(owner, owner.id == CaseOwnership.office_id)
        .outerjoin(unit, unit.id == CaseOwnership.unit_office_id)
        .outerjoin(officer, officer.id == CaseOwnership.officer_user_id)
        .where(
            CaseOwnership.case_id.in_(case_ids),
            CaseOwnership.status == OwnershipStatus.ACTIVE,
            CaseOwnership.role == OwnershipRole.PRIMARY,
        )
    ).all()
    return {
        cid: {
            "owner_code": owner_code,
            "allotment": {
                "unit": {"code": u_code, "name": u_name} if u_code else None,
                "officer": {"id": o_id, "full_name": o_name} if o_id else None,
            },
        }
        for cid, owner_code, u_code, u_name, o_id, o_name in rows
    }


def case_briefs(session: Session, user: User, case_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
    """Batched: per case, the latest stage, the custody brief (`with_me` relative to `user`; no remark), the
    active primary ownership's unit and officer, and the owner's office code. Three queries for the page."""
    ids = list(dict.fromkeys(case_ids))
    if not ids:
        return {}
    stages = _stage_briefs(session, ids)
    custody_ = _custody_briefs(session, user, ids)
    owners = _allotments(session, ids)
    return {
        cid: {
            "stage": stages.get(cid),
            "custody": custody_.get(cid),
            "allotment": owners[cid]["allotment"] if cid in owners else None,
            "owner_code": owners[cid]["owner_code"] if cid in owners else None,
        }
        for cid in ids
    }
