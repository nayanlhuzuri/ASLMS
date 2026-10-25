"""Custody and file movement (design `custody-workflow`, on the owner's rules of 7 Oct 2026).

- **Custody is accountability.** `custody` names where a claimed case is now: the holder office, the holder
  officer and the holder **membership** (office + officer + designation), with the pending action, since and
  due date of that holder. Every movement is one append-only `custody_history` leg with the sender's snapshot.
- **Sending the file** (decisions 3-5) replaces requests and hand-over: the holder (holding is the authority, no
  function needed) or, for a leg that names an office only, a `custody.move` holder who controls that office,
  sends the file to an officer (an active membership of any department) with a remark, a pending action and an
  optional due date. A chain, as in eOffice; nothing waits on anything else.
- **Recall** (decision 6): a membership holding `custody.recall` in the owning department calls the file back
  from wherever it is, in one step, and becomes the holder (`examine`, no due date).
- **Ownership never moves with custody**; ownership moves still write legs (claimed, allotted, taken over,
  transferred) and the exit step of `user-memberships` writes `reassigned_on_exit`.
- `move_custody` is the only writer of `custody` / `custody_history`; when the holder membership changes it
  makes the previous holder's drafts permanent in the same transaction (decision 13). The caller holds the case
  row lock. Events and audit rows never carry the remark text (decision 21).
- Reading: `card` (the overview's custody card), `history`, `held` (decision 24), `sent`, `summary` (24a),
  `recipients` (the send targets)."""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import Select, exists, false, func, or_, select
from sqlalchemy.orm import Session, aliased

from aslms.core.config import get_settings
from aslms.domain.cases import Case
from aslms.domain.org import Office, User, UserMembership
from aslms.domain.ownership import CaseOwnership, OwnershipRole, OwnershipStatus
from aslms.domain.reference import EventType, Permission, RefRole, Role, Stage
from aslms.domain.workflow import (
    CUSTODY_REASON_LABELS,
    CUSTODY_REASONS,
    PENDING_ACTION_LABELS,
    REMARK_REASONS,
    Custody,
    CustodyHistory,
    PendingAction,
)
from aslms.services import access, case_filters, inbox, visibility
from aslms.services.access import Member
from aslms.services.audit import Actor, snapshot, write_audit
from aslms.services.case_filters import CaseFilters
from aslms.services.cases import emit_event
from aslms.services.workflow_common import (
    REMARK_MAX,
    REMARK_MIN,
    bad,
    check_due,
    clean_text,
    conflict,
    digest,
    forbidden,
    lock_case,
    pending_action,
    require_owned,
    require_visible_basis,
    today_ist,
    value,
)

REASONS = frozenset(CUSTODY_REASONS)
SENT_LIST_REASONS = ("sent", "recalled")
HELD_SCOPES = ("me", "office", "owned")
HISTORY_ORDERS = ("asc", "desc")
DEFAULT_DUE_SOON_DAYS = 2


def _now() -> datetime:
    return datetime.now(UTC)


# ------------------------------------------------------------------------------------------------ the writer


def move_custody(
    session: Session,
    actor: Actor,
    case: Case,
    *,
    office: Office,
    user: User | None = None,
    membership: UserMembership | None = None,
    reason: str,
    pending_action: PendingAction = PendingAction.NONE,
    due_date: date | None = None,
    remark: str | None = None,
    extra: dict[str, Any] | None = None,
) -> CustodyHistory:
    """Writes the leg and the custody row; when the holder membership changes, the previous holder's drafts
    become permanent here (decision 13: a file never moves leaving drafts behind). The leg carries the list of
    the finalised notes' `ref_no` as `leg.finalised_ref_nos` (not a column). Emits `custody_moved` (never the
    remark). The caller holds the case row lock."""
    from aslms.services import notes

    if reason not in REASONS:
        raise ValueError(f"unknown custody reason {reason!r}")
    if reason in REMARK_REASONS and not (remark or "").strip():
        raise ValueError(f"a {reason} leg needs a remark")
    if membership is not None and user is None:
        user = session.get(User, membership.user_id)
    now = _now()
    row = session.get(Custody, case.id)
    previous_membership_id = row.holder_membership_id if row is not None else None
    previous_user_id = row.holder_user_id if row is not None else None
    previous_office = session.get(Office, row.holder_office_id) if row is not None else None
    seq = int(
        session.scalar(select(func.max(CustodyHistory.seq_no)).where(CustodyHistory.case_id == case.id)) or 0
    )
    leg = CustodyHistory(
        case_id=case.id,
        seq_no=seq + 1,
        holder_office_id=office.id,
        holder_office_code=office.code,
        holder_user_id=user.id if user else None,
        holder_user_name=user.full_name if user else None,
        holder_membership_id=membership.id if membership else None,
        holder_designation=(membership.designation or None) if membership else None,
        reason=reason,
        pending_action=pending_action,
        due_date=due_date,
        remark=(remark or "").strip()[:REMARK_MAX] or None,
        started_at=now,
        **snapshot(actor),
    )
    session.add(leg)
    session.flush()
    if row is None:
        row = Custody(case_id=case.id, holder_office_id=office.id)
        session.add(row)
    row.holder_office_id = office.id
    row.holder_user_id = user.id if user else None
    row.holder_membership_id = membership.id if membership else None
    row.pending_action = pending_action
    row.since = now
    row.due_date = due_date
    row.current_leg_id = leg.id
    session.flush()
    finalised: list[str] = []
    if previous_membership_id is not None and previous_membership_id != leg.holder_membership_id:
        finalised = notes.finalise_drafts(session, actor, case, previous_membership_id)
    leg.finalised_ref_nos = finalised  # type: ignore[attr-defined]
    emit_event(
        session,
        EventType.CUSTODY_MOVED,
        case,
        {
            "office_code": office.code,
            "user_id": str(user.id) if user else None,
            "user_name": user.full_name if user else None,
            "holder_designation": leg.holder_designation,
            "membership_id": str(membership.id) if membership else None,
            "reason": reason,
            "pending_action": PendingAction(pending_action).value,
            "due_date": due_date.isoformat() if due_date else None,
            "seq_no": leg.seq_no,
            "previous_user_id": str(previous_user_id) if previous_user_id else None,
            "previous_membership_id": str(previous_membership_id) if previous_membership_id else None,
            "previous_office_code": previous_office.code if previous_office else None,
            "finalised_notes": len(finalised),
            **{k: v for k, v in (extra or {}).items() if k != "remark"},
        },
        dedupe=f"custody_moved:{case.id}:{leg.seq_no}",
        actor_user_id=actor.user_id,
    )
    return leg


# ------------------------------------------------------------------------------------------------ who holds


def holder_member(session: Session, user: User | Member, custody: Custody | None) -> Member | None:
    """The caller's membership that holds the file (decision 4a), or None."""
    if custody is None:
        return None
    if custody.holder_membership_id is not None:
        return next(
            (m for m in access.members(session, user) if m.membership_id == custody.holder_membership_id),
            None,
        )
    if custody.holder_user_id is None:
        return None
    # a leg naming a person without a membership (not written since 0009): the person's membership covering it
    office = session.get(Office, custody.holder_office_id)
    return next(
        (
            m
            for m in access.members(session, user)
            if m.id == custody.holder_user_id and office is not None and m.covers(office)
        ),
        None,
    )


def controls_office(session: Session, member: Member, office: Office) -> bool:
    """Decision 4b: a membership at the office (when it is not Department-tier), or a whole-department
    membership of the department containing it."""
    if not access.is_department(office) and member.office.id == office.id:
        return True
    return (
        member.department is not None
        and visibility.whole_department(session, member)
        and visibility.in_subtree(office, member.department)
    )


def controller_member(session: Session, user: User | Member, custody: Custody | None) -> Member | None:
    """For a leg that names an office only: the caller's membership holding `custody.move` that controls it."""
    if custody is None or custody.holder_membership_id is not None or custody.holder_user_id is not None:
        return None
    office = session.get(Office, custody.holder_office_id)
    for m in access.members(session, user):
        if m.holds(Permission.CUSTODY_MOVE) and office is not None and controls_office(session, m, office):
            return m
    return None


def controls_custody(session: Session, user: User | Member, custody: Custody | None) -> Member | None:
    """The membership that may send the file on (decision 4), or None."""
    return holder_member(session, user, custody) or controller_member(session, user, custody)


def recaller_member(session: Session, user: User | Member, case: Case) -> Member | None:
    """The caller's membership holding `custody.recall` in the owning department (decision 6), or None."""
    from aslms.services.workflow_common import primary_owner

    owner = primary_owner(session, case)
    if owner is None:
        return None
    return next(
        (
            m
            for m in access.holders_in(session, user, Permission.CUSTODY_RECALL)
            if m.department is not None and m.department.id == owner.office_id
        ),
        None,
    )


# ------------------------------------------------------------------------------------------------ targets


def eligible_target(session: Session, membership: UserMembership | None) -> bool:
    """Decision 3: an active membership of an active login at an active office inside an active
    Department-tier office, of any type but the State-wide ones."""
    if membership is None or not membership.is_active or membership.department_id is None:
        return False
    if Role(value(membership.role)) in access.NOT_OFFICERS:
        return False
    user = session.get(User, membership.user_id)
    office = session.get(Office, membership.office_id)
    dept = session.get(Office, membership.department_id)
    return (
        user is not None
        and user.is_active
        and office is not None
        and office.is_active
        and dept is not None
        and dept.is_active
        and access.is_department(dept)
        and visibility.in_subtree(office, dept)
    )


def _membership_ref(session: Session, raw: Any) -> UserMembership | None:
    try:
        return session.get(UserMembership, raw if isinstance(raw, uuid.UUID) else uuid.UUID(str(raw)))
    except (TypeError, ValueError):
        return None


def _departments(session: Session) -> list[Office]:
    rows = session.scalars(
        select(Office)
        .where(
            Office.is_active.is_(True),
            Office.parent_id.is_not(None),
            Office.kind.in_(list(access.DEPARTMENT_TIER_KINDS)),
        )
        .order_by(Office.code)
    ).all()
    return [o for o in rows if access.is_department(o)]


def recipients(
    session: Session,
    user: User | Member,
    *,
    department: str | None = None,
    q: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> inbox.Page:
    """Decision 3's targets: without `department`, the active Department-tier offices; with it, the eligible
    memberships of that department's subtree (filtered by `q` over name, designation and office code), each
    with the person's `user_id`, and `units`: the active offices strictly inside the department, by path
    (design `portal-cases`, decision 14d)."""
    if not department:
        items = [{"code": o.code, "name": o.name} for o in _departments(session)]
        return inbox.Page(items, len(items))
    dept = session.scalar(select(Office).where(Office.code == department.strip().upper()))
    if dept is None or not dept.is_active or not access.is_department(dept):
        raise bad(f"{department!r} is not an active department")
    stmt = (
        select(UserMembership, User, Office)
        .join(User, User.id == UserMembership.user_id)
        .join(Office, Office.id == UserMembership.office_id)
        .where(
            UserMembership.is_active.is_(True),
            UserMembership.department_id == dept.id,
            User.is_active.is_(True),
            Office.is_active.is_(True),
            UserMembership.role.notin_([r.value for r in access.NOT_OFFICERS]),
            or_(Office.id == dept.id, Office.path.like(dept.path + "/%")),
        )
    )
    text_q = (q or "").strip()
    if text_q:
        like = f"%{text_q}%"
        stmt = stmt.where(
            or_(User.full_name.ilike(like), UserMembership.designation.ilike(like), Office.code.ilike(like))
        )
    limit, offset = inbox.clamp(limit, offset)
    total = int(session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0)
    rows = session.execute(
        stmt.order_by(User.full_name, Office.code, UserMembership.id).limit(limit).offset(offset)
    ).all()
    labels = {r.code: r.label for r in session.scalars(select(RefRole)).all()}
    items = [
        {
            "membership_id": m.id,
            "user_id": u.id,
            "full_name": u.full_name,
            "designation": m.designation,
            "office_code": o.code,
            "office_name": o.name,
            "role_label": labels.get(value(m.role), value(m.role)),
        }
        for m, u, o in rows
    ]
    units = [
        {"code": o.code, "name": o.name}
        for o in session.scalars(
            select(Office)
            .where(Office.is_active.is_(True), Office.path.like(dept.path + "/%"))
            .order_by(Office.path)
        ).all()
    ]
    return inbox.Page(items, total, {"units": units})


# ------------------------------------------------------------------------------------------------ send / recall


@dataclass
class MoveResult:
    leg: CustodyHistory
    finalised: list[str] = field(default_factory=list)


def _custody_or_conflict(session: Session, case: Case) -> Custody:
    row = session.get(Custody, case.id)
    if row is None:
        raise conflict("not_owned", "the case has no custody record")
    return row


def send(
    session: Session,
    actor: Actor,
    user: User | Member,
    case: Case,
    *,
    to_membership: Any,
    pending_action_: Any,
    due_date: date | None = None,
    remark: str | None,
    stage: str | None = None,
) -> MoveResult:
    """Decisions 3, 4, 13, 19. Order: visible (404) → fields (400) → lock → claimed (409 `not_owned`) → control
    (403 `not_in_control`) → target (400 `bad_target`, 409 `unchanged`) → stage function (403) → leg, stage,
    audit."""
    from aslms.services import stages

    require_visible_basis(session, user, case)
    remark_t = clean_text(remark, "remark", min_len=REMARK_MIN, max_len=REMARK_MAX)
    action = pending_action(pending_action_)
    due = check_due(due_date)
    stage_ref = stages.check_stage(session, stage) if stage else None
    lock_case(session, case)
    require_owned(session, case)
    custody = _custody_or_conflict(session, case)
    sender = controls_custody(session, user, custody)
    if sender is None:
        raise forbidden(
            "not_in_control",
            "only the officer the case is with (or, for a case with an office, its controller) may send it",
        )
    target = _membership_ref(session, to_membership)
    if not eligible_target(session, target):
        raise bad("to_membership is not an active officer of a department", "bad_target")
    if target.id == custody.holder_membership_id:
        raise conflict("unchanged", "the case is already with that officer")
    if stage_ref is not None and not sender.holds(Permission.STAGES_SET):
        raise forbidden("forbidden", "stages.set is not enabled for you; send without a stage")
    actor = access.actor_as(actor, sender)
    office = session.get(Office, target.office_id)
    before = card_summary(session, custody)
    leg = move_custody(
        session,
        actor,
        case,
        office=office,
        membership=target,
        reason="sent",
        pending_action=action,
        due_date=due,
        remark=remark_t,
    )
    stage_row = None
    if stage_ref is not None:
        stage_row = stages.set_stage(
            session, actor, user, case, stage=Stage(stage_ref.code).value, member=sender, checked=True
        )
    finalised = list(getattr(leg, "finalised_ref_nos", []))
    write_audit(
        session,
        actor,
        "custody.sent",
        "custody_history",
        leg.id,
        case_id=case.id,
        before=before,
        after={
            "seq_no": leg.seq_no,
            "to_membership_id": str(target.id),
            "to_office_code": office.code,
            "to_user_id": str(target.user_id),
            "pending_action": action.value,
            "due_date": due,
            "remark": digest(remark_t),
            "stage": stage_ref.code if stage_row is not None else None,
            "finalised_notes": finalised,
        },
    )
    return MoveResult(leg, finalised)


def recall(
    session: Session, actor: Actor, user: User | Member, case: Case, *, remark: str | None
) -> MoveResult:
    """Decision 6: `custody.recall` in a membership of the owning department; the recaller becomes the holder
    (`examine`, no due date)."""
    require_visible_basis(session, user, case)
    remark_t = clean_text(remark, "remark", min_len=REMARK_MIN, max_len=REMARK_MAX)
    if not access.has(session, user, Permission.CUSTODY_RECALL):
        raise forbidden("function_missing", "custody.recall is not enabled for you")
    lock_case(session, case)
    require_owned(session, case)
    custody = _custody_or_conflict(session, case)
    recaller = recaller_member(session, user, case)
    if recaller is None:
        raise forbidden(
            "not_owner_department",
            "custody.recall works only in a membership of the department that owns the case",
        )
    if custody.holder_membership_id == recaller.membership_id:
        raise conflict("unchanged", "this case is already with you")
    actor = access.actor_as(actor, recaller)
    before = card_summary(session, custody)
    leg = move_custody(
        session,
        actor,
        case,
        office=recaller.office,
        membership=recaller.membership,
        reason="recalled",
        pending_action=PendingAction.EXAMINE,
        remark=remark_t,
    )
    finalised = list(getattr(leg, "finalised_ref_nos", []))
    write_audit(
        session,
        actor,
        "custody.recalled",
        "custody_history",
        leg.id,
        case_id=case.id,
        before=before,
        after={
            "seq_no": leg.seq_no,
            "membership_id": str(recaller.membership_id),
            "office_code": recaller.office.code,
            "remark": digest(remark_t),
            "finalised_notes": finalised,
        },
    )
    return MoveResult(leg, finalised)


# ------------------------------------------------------------------------------------------------ reading


def card_summary(session: Session, custody: Custody) -> dict[str, Any]:
    """What an audit `before` says about the custody row (references and codes only)."""
    office = session.get(Office, custody.holder_office_id)
    return {
        "holder_office_code": office.code if office else None,
        "holder_user_id": str(custody.holder_user_id) if custody.holder_user_id else None,
        "holder_membership_id": str(custody.holder_membership_id) if custody.holder_membership_id else None,
        "pending_action": value(custody.pending_action),
        "due_date": custody.due_date,
    }


def shows_remark(session: Session, user: User | Member, case: Case) -> bool:
    """Decision 11 as narrowed by design `alerts-visibility-roles`, decision 16: the remark is shown to callers with a
    working basis through any membership (read per membership, design followups-oct, decision 18), and to a
    State-wide reader only when they hold `cases.view_private_all` (the super admin and, by default, the Auditor).
    State oversight and the central operator see the leg without the remark."""
    if visibility.working_names(session, user, case):
        return True
    return visibility.state_wide(session, user) and visibility.sees_private_all(session, user)


def _office_ref(o: Office | None) -> dict[str, Any] | None:
    return {"code": o.code, "name": o.name} if o is not None else None


def leg_out(session: Session, leg: CustodyHistory, *, show_remark: bool) -> dict[str, Any]:
    office = session.get(Office, leg.holder_office_id)
    action = PendingAction(leg.pending_action)
    return {
        "seq_no": leg.seq_no,
        "holder_office": _office_ref(office)
        or {"code": leg.holder_office_code, "name": leg.holder_office_code},
        "holder_user": (
            {"id": leg.holder_user_id, "full_name": leg.holder_user_name} if leg.holder_user_id else None
        ),
        "holder_designation": leg.holder_designation,
        "reason": leg.reason,
        "reason_label": CUSTODY_REASON_LABELS.get(leg.reason, leg.reason),
        "pending_action": action.value,
        "pending_action_label": PENDING_ACTION_LABELS[action],
        "due_date": leg.due_date,
        "remark": leg.remark if show_remark else None,
        "started_at": leg.started_at,
        "actor_name": leg.actor_name,
        "actor_designation": leg.actor_designation,
        "actor_office_code": leg.actor_office_code,
    }


def card(
    session: Session, user: User | Member, case: Case, *, bases: list[str] | None = None
) -> dict[str, Any] | None:
    """Decision 25: the custody card of the overview, `held` and the custody tab."""
    row = session.get(Custody, case.id)
    if row is None:
        return None
    if bases is None:
        bases = visibility.access_basis(session, user, case)
    office = session.get(Office, row.holder_office_id)
    holder = session.get(User, row.holder_user_id) if row.holder_user_id else None
    leg = session.get(CustodyHistory, row.current_leg_id) if row.current_leg_id else None
    designation = leg.holder_designation if leg is not None else None
    if designation is None and row.holder_membership_id is not None:
        m = session.get(UserMembership, row.holder_membership_id)
        designation = m.designation if m is not None else None
    action = PendingAction(row.pending_action)
    today = today_ist()
    overdue = row.due_date is not None and row.due_date < today
    # design case-workspace-admin, decision 19: the same window as `summary` (`request_due_soon_days`)
    due_soon = (
        not overdue
        and row.due_date is not None
        and row.due_date <= today + timedelta(days=get_settings().request_due_soon_days)
    )
    recaller = recaller_member(session, user, case)
    return {
        "holder_office": _office_ref(office),
        "holder_user": (
            {"id": holder.id, "full_name": holder.full_name, "designation": designation} if holder else None
        ),
        "pending_action": action.value,
        "pending_action_label": PENDING_ACTION_LABELS[action],
        "since": row.since,
        "due_date": row.due_date,
        "overdue": overdue,
        "overdue_days": (today - row.due_date).days if overdue else 0,
        "due_soon": due_soon,
        "sent_by": (
            {
                "name": leg.actor_name,
                "designation": leg.actor_designation,
                "office_code": leg.actor_office_code,
            }
            if leg is not None and leg.actor_name
            else None
        ),
        "reason": leg.reason if leg is not None else None,
        "remark": leg.remark if leg is not None and shows_remark(session, user, case) else None,
        "leg_seq_no": leg.seq_no if leg is not None else None,
        "can_send": controls_custody(session, user, row) is not None,
        "can_recall": recaller is not None and recaller.membership_id != row.holder_membership_id,
    }


def history(
    session: Session,
    user: User | Member,
    case: Case,
    *,
    limit: int | None = None,
    offset: int | None = None,
    order: str = "asc",
) -> dict[str, Any]:
    """The card and the legs by `seq_no`, oldest first (`order="asc"`) or newest first (`"desc"`, design
    `case-workspace-admin`: the rail's journey and the remarks history page from the newest). `remarks_shown`
    tells whether the legs carry their remark for this caller (`shows_remark`), so the portal never infers it."""
    if order not in HISTORY_ORDERS:
        raise bad("order must be asc or desc")
    bases = visibility.require_visible(session, user, case)
    stmt = select(CustodyHistory).where(CustodyHistory.case_id == case.id)
    limit, offset = inbox.clamp(limit, offset)
    total = int(session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    by = CustodyHistory.seq_no.desc() if order == "desc" else CustodyHistory.seq_no
    legs = session.scalars(stmt.order_by(by).limit(limit).offset(offset)).all()
    show = shows_remark(session, user, case)
    return {
        "card": card(session, user, case, bases=bases),
        "legs": [leg_out(session, leg, show_remark=show) for leg in legs],
        "total": total,
        "remarks_shown": show,
    }


def _tracked_departments(session: Session, user: User | Member) -> list[Office]:
    out: list[Office] = []
    for m in access.holders_in(session, user, Permission.CUSTODY_TRACK):
        if m.department is not None and all(d.id != m.department.id for d in out):
            out.append(m.department)
    return out


# `held` reads custody under an alias: the visibility rule's custody basis is a correlated EXISTS over `custody`,
# which must not correlate to the listed row's table
HELD = aliased(Custody, name="held_custody")


def _owned_by(depts: list[Office], custody_=Custody):
    return exists().where(
        CaseOwnership.case_id == custody_.case_id,
        CaseOwnership.status == OwnershipStatus.ACTIVE,
        CaseOwnership.role == OwnershipRole.PRIMARY,
        CaseOwnership.office_id.in_([d.id for d in depts]),
    )


def _held_stmt(session: Session, user: User | Member, scope: str) -> Select:
    stmt = (
        select(HELD, Case)
        .join(Case, Case.id == HELD.case_id)
        .where(visibility.visible_case_condition(session, user))
    )
    if scope == "me":
        uid = user.id
        return stmt.where(HELD.holder_user_id == uid)
    if scope == "office":
        roots: list[Office] = []
        for m in access.members(session, user):
            whole = m.department is not None and visibility.whole_department(session, m)
            roots.append(m.department if whole else m.office)
        if not roots:
            return stmt.where(false())
        return stmt.where(or_(*[HELD.holder_office_id.in_(visibility.subtree_ids(r)) for r in roots]))
    depts = _tracked_departments(session, user)
    if not depts:
        raise forbidden("forbidden", "custody.track in a department is needed for scope=owned")
    return stmt.where(_owned_by(depts, HELD))


def held(
    session: Session,
    user: User | Member,
    *,
    scope: str = "me",
    overdue: bool | None = None,
    holder_department: str | None = None,
    filters: CaseFilters | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> inbox.Page:
    """Decision 24: the cases held by the caller (`me`), by their offices (`office`), or owned by a department
    they track, wherever held (`owned`, decision 24a); always ANDed with the case visibility rule; ordered by
    due date, then since. `filters`: the shared case filters (design `portal-filters`), on the held case."""
    if scope not in HELD_SCOPES:
        raise bad("scope must be me, office or owned")
    stmt = _held_stmt(session, user, scope)
    today = today_ist()
    if overdue is True:
        stmt = stmt.where(HELD.due_date < today)
    elif overdue is False:
        stmt = stmt.where(or_(HELD.due_date.is_(None), HELD.due_date >= today))
    if holder_department:
        dept = session.scalar(select(Office).where(Office.code == holder_department.strip().upper()))
        if dept is None:
            raise bad(f"unknown department {holder_department!r}")
        stmt = stmt.where(HELD.holder_office_id.in_(visibility.subtree_ids(dept)))
    for cond in case_filters.conditions(session, filters):
        stmt = stmt.where(cond)
    limit, offset = inbox.clamp(limit, offset)
    total = int(session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0)
    rows = session.execute(
        stmt.order_by(HELD.due_date.asc().nulls_last(), HELD.since, HELD.case_id).limit(limit).offset(offset)
    ).all()
    summaries = inbox.summaries(session, [c for _, c in rows])
    return inbox.Page([{"case": summaries[c.id], "card": card(session, user, c)} for _, c in rows], total)


def sent(
    session: Session,
    user: User | Member,
    *,
    filters: CaseFilters | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> inbox.Page:
    """Decision 24: the legs the caller wrote (sends and recalls), with the case summary (searchable facts) and
    the leg; the remark is the caller's own. Detail still needs the case visibility. `filters`: the shared case
    filters on the leg's case (design `portal-filters`, decision 8: they match the facts the row shows)."""
    stmt = (
        select(CustodyHistory, Case)
        .join(Case, Case.id == CustodyHistory.case_id)
        .where(CustodyHistory.actor_user_id == user.id, CustodyHistory.reason.in_(SENT_LIST_REASONS))
        .where(*case_filters.conditions(session, filters))
    )
    limit, offset = inbox.clamp(limit, offset)
    total = int(session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0)
    rows = session.execute(
        stmt.order_by(CustodyHistory.created_at.desc(), CustodyHistory.id.desc()).limit(limit).offset(offset)
    ).all()
    summaries = inbox.summaries(session, [c for _, c in rows])
    ids = list({c.id for _, c in rows})
    current_legs = (
        dict(
            session.execute(
                select(Custody.case_id, Custody.current_leg_id).where(Custody.case_id.in_(ids))
            ).all()
        )
        if ids
        else {}
    )
    seen = (
        set(
            session.scalars(
                select(Case.id).where(Case.id.in_(ids), visibility.visible_case_condition(session, user))
            ).all()
        )
        if ids
        else set()
    )
    return inbox.Page(
        [
            {
                "case": summaries[c.id],
                "leg": leg_out(session, leg, show_remark=True),
                "visible": c.id in seen,
                # design case-workspace-admin, decision 20: null when the sender can no longer open the case
                "current": (current_legs.get(c.id) == leg.id) if c.id in seen else None,
            }
            for leg, c in rows
        ],
        total,
    )


def summary(
    session: Session,
    user: User | Member,
    *,
    department: str | None = None,
    soon_days: int = DEFAULT_DUE_SOON_DAYS,
) -> dict[str, Any]:
    """Decision 24a: per department the caller tracks, counts only — files held, due within the window,
    overdue, by holder department and by holder office/officer."""
    depts = _tracked_departments(session, user)
    if not depts:
        raise forbidden("forbidden", "custody.track is not enabled for you in any department")
    if department:
        code = department.strip().upper()
        depts = [d for d in depts if d.code == code]
        if not depts:
            raise forbidden("forbidden", f"you do not track {code}")
    return {"departments": summary_for(session, depts, soon_days=soon_days)}


def summary_for(
    session: Session,
    depts: list[Office],
    *,
    soon_days: int = DEFAULT_DUE_SOON_DAYS,
    today: date | None = None,
) -> list[dict[str, Any]]:
    """Decision 24a's counts for the given departments, without the `custody.track` check (design
    `reports-dashboards`: the department dashboard and the reports call it under their own gates). Per
    department: files held (every custody row of its primary-owned cases), due within `soon_days`, overdue, by
    holder department and by holder office/officer; plus, for the dashboard, files with a pending action, those
    without a due date (`pending_no_due_date`) and the counts by holder office (`by_holder_office`). One query;
    names and designations come from the current leg's snapshot."""
    today = today or today_ist()
    if not depts:
        return []
    leg = aliased(CustodyHistory, name="current_leg")
    rows = session.execute(
        select(
            CaseOwnership.office_id,
            Custody.due_date,
            Custody.pending_action,
            Office.code,
            Office.name,
            Office.path,
            leg.holder_user_name,
            leg.holder_designation,
        )
        .select_from(Custody)
        .join(Office, Office.id == Custody.holder_office_id)
        .join(
            CaseOwnership,
            (CaseOwnership.case_id == Custody.case_id)
            & (CaseOwnership.status == OwnershipStatus.ACTIVE)
            & (CaseOwnership.role == OwnershipRole.PRIMARY),
        )
        .outerjoin(leg, leg.id == Custody.current_leg_id)
        .where(CaseOwnership.office_id.in_([d.id for d in depts]))
    ).all()
    dept_codes = {
        o.code
        for o in session.scalars(
            select(Office).where(Office.code.in_({(r.path.split("/") + ["", ""])[1] for r in rows}))
        ).all()
        if access.is_department(o)
    }
    per: dict[Any, dict[str, Any]] = {
        d.id: {"totals": Counter(), "by_dept": {}, "by_holder": {}, "by_office": {}} for d in depts
    }
    for owner_id, due, action, code, name, path, user_name, designation in rows:
        flags = {"held": 1}
        if due is not None and due < today:
            flags["overdue"] = 1
        elif due is not None and due <= today + timedelta(days=soon_days):
            flags["due_soon"] = 1
        if PendingAction(action) != PendingAction.NONE:
            flags["with_pending_action"] = 1
            if due is None:
                flags["pending_no_due_date"] = 1
        parts = path.split("/")
        dkey = parts[1] if len(parts) >= 2 and parts[1] in dept_codes else code
        bucket = per[owner_id]
        for k, v in flags.items():
            bucket["totals"][k] += v
            bucket["by_dept"].setdefault(dkey, Counter())[k] += v
            bucket["by_holder"].setdefault((code, user_name, designation), Counter())[k] += v
            bucket["by_office"].setdefault((dkey, code, name), Counter())[k] += v
    out = []
    for dept in depts:
        b = per[dept.id]
        totals = b["totals"]
        out.append(
            {
                "code": dept.code,
                "held": totals["held"],
                "due_soon": totals["due_soon"],
                "overdue": totals["overdue"],
                "with_pending_action": totals["with_pending_action"],
                "pending_no_due_date": totals["pending_no_due_date"],
                "by_holder_department": [
                    {"code": k, "held": v["held"], "due_soon": v["due_soon"], "overdue": v["overdue"]}
                    for k, v in sorted(b["by_dept"].items())
                ],
                "by_holder": [
                    {
                        "office_code": k[0],
                        "user_name": k[1],
                        "designation": k[2],
                        "held": v["held"],
                        "due_soon": v["due_soon"],
                        "overdue": v["overdue"],
                    }
                    for k, v in sorted(b["by_holder"].items(), key=lambda kv: (kv[0][0], kv[0][1] or ""))
                ],
                "by_holder_office": [
                    {
                        "holder_department_code": k[0],
                        "office_code": k[1],
                        "office_name": k[2],
                        "held": v["held"],
                        "with_pending_action": v["with_pending_action"],
                        "due_soon": v["due_soon"],
                        "overdue": v["overdue"],
                    }
                    for k, v in sorted(b["by_office"].items())
                ],
            }
        )
    return out
