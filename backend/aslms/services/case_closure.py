"""Close Case and Reopen Case (design `close-case`): a department's own view of a claimed case is **Open** or
**Closed**, separate from the court's status.

- A case is Closed while it has a `case_closures` row with `reopened_at IS NULL` (decision 1). This module is the
  only writer of `case_closures`: `close` inserts; `reopen_on_court_status` and `reopen` update the one row once.
- **Closing** (decisions 3-7): `cases.close` in the acting membership, standing as the holder of the owning
  department, its head, or the super admin; the case claimed, not already closed, disposed by the court and with no
  transfer waiting. One transaction: the `closed` leg to the owning department's office (the holder's drafts become
  permanent there), the `closing` note (case scope), the closure row, the `case_closed` event and the `case.closed`
  audit row. Never the remark text in the event or the audit row.
- **Reopening** (decisions 10-13, 18): automatically when the court's status reads `pending` while a closure is open
  (`unknown` never reopens), or by hand with a reason by a `cases.reopen` membership of the owning department or the
  super admin. Either way a `reopened` leg to the owning department's office with `examine` pending, the closure's
  reopening columns, the `case_reopened` event and the `case.reopened` audit row; a manual reopen adds the
  `reopening` note and the reopener's snapshot.
- Reading: `closed_condition` (a correlated EXISTS for the lists), `open_closure`, `brief`, and the flags
  `close_flags` / `reopen_flags` the case page reads, computed by the same checks without locking or writing."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import ColumnElement, exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from aslms.domain.cases import Case, CaseStatus
from aslms.domain.org import Office, User
from aslms.domain.ownership import CaseOwnership, OwnershipTransfer, TransferStatus
from aslms.domain.reference import EventType, NoteKind, Permission
from aslms.domain.workflow import CaseClosure, CaseNote, Custody, CustodyHistory, PendingAction
from aslms.services import access, visibility
from aslms.services.access import Member
from aslms.services.audit import Actor, snapshot, write_audit
from aslms.services.cases import emit_event
from aslms.services.workflow_common import (
    REMARK_MAX,
    REMARK_MIN,
    clean_text,
    conflict,
    digest,
    forbidden,
    lock_case,
    primary_owner,
    require_visible_basis,
)

COURT_STATUS_ACTOR = "court status"

# the plain words of each refusal (design close-case, decision 25); the portal shows its own copy of the same text
CASE_CLOSED_MESSAGE = (
    "This case is closed. It opens again when the court's status changes or when it is reopened."
)
MESSAGES = {
    "not_owned": "The case has not been claimed by a department, so it cannot be closed.",
    "not_disposed": "The court has not disposed of this case, so it cannot be closed.",
    "already_closed": "This case is already closed.",
    "not_closer": (
        "Only an officer of the owning department who has the case, the Head of Department or the Super "
        "Administrator can close it."
    ),
    "transfer_open": "A transfer of this case is waiting for a decision. Decide or withdraw it first.",
    "not_closed": "This case is not closed.",
    "not_reopener": "Only the owning department or the Super Administrator can reopen this case.",
    "concurrent_change": "The case changed at the same time; try again.",
}


def _now() -> datetime:
    return datetime.now(UTC)


# ------------------------------------------------------------------------------------------------ reading


def closed_condition(case_id_col: Any) -> ColumnElement[bool]:
    """The case named by `case_id_col` has an open closure (a fresh alias per call, so it never correlates to a
    closure row of the enclosing query)."""
    cc = aliased(CaseClosure)
    return exists().where(cc.case_id == case_id_col, cc.reopened_at.is_(None))


def closed_at_column(case_id_col: Any) -> Any:
    """The open closure's `closed_at` (a scalar subquery; NULL for an open case): the order of the Closed lists."""
    cc = aliased(CaseClosure)
    return (
        select(cc.closed_at)
        .where(cc.case_id == case_id_col, cc.reopened_at.is_(None))
        .limit(1)
        .scalar_subquery()
    )


def closed_ids(session: Session, case_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """Of `case_ids`, the cases that are closed now (one query)."""
    ids = list(dict.fromkeys(case_ids))
    if not ids:
        return set()
    return set(
        session.scalars(
            select(CaseClosure.case_id).where(CaseClosure.case_id.in_(ids), CaseClosure.reopened_at.is_(None))
        ).all()
    )


def is_closed(session: Session, case: Case | uuid.UUID) -> bool:
    case_id = case if isinstance(case, uuid.UUID) else case.id
    return bool(session.scalar(select(closed_condition(case_id))))


def open_closure(session: Session, case: Case, *, lock: bool = False) -> CaseClosure | None:
    stmt = select(CaseClosure).where(CaseClosure.case_id == case.id, CaseClosure.reopened_at.is_(None))
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return session.scalar(stmt)


def latest_closure(session: Session, case: Case) -> CaseClosure | None:
    return session.scalar(
        select(CaseClosure)
        .where(CaseClosure.case_id == case.id)
        .order_by(CaseClosure.closed_at.desc(), CaseClosure.id.desc())
        .limit(1)
    )


def _open_transfer(session: Session, case: Case) -> bool:
    return bool(
        session.scalar(
            select(
                exists().where(
                    OwnershipTransfer.case_id == case.id, OwnershipTransfer.status == TransferStatus.REQUESTED
                )
            )
        )
    )


def closer_member(
    session: Session,
    user: User | Member,
    case: Case,
    custody: Custody | None,
    owner: CaseOwnership | None = None,
) -> tuple[Member, str] | None:
    """Decision 3: the acting membership and its standing, tried in order — the holder membership when it belongs
    to the owning department (`holder`), the owning department's active head membership (`head`), the super admin
    membership (`super_admin`). Every candidate must hold `cases.close`."""
    from aslms.services import custody as custody_svc
    from aslms.services import memberships

    owner = owner or primary_owner(session, case)
    if owner is None:
        return None
    holder = custody_svc.holder_member(session, user, custody)
    if (
        holder is not None
        and holder.holds(Permission.CASES_CLOSE)
        and holder.department is not None
        and holder.department.id == owner.office_id
    ):
        return holder, "holder"
    owner_office = session.get(Office, owner.office_id)
    head = memberships.head_of(session, owner_office) if owner_office is not None else None
    if head is not None:
        m = next((m for m in access.members(session, user) if m.membership_id == head.id), None)
        if m is not None and m.holds(Permission.CASES_CLOSE):
            return m, "head"
    sa_member = access.super_admin_member(session, user)
    if sa_member is not None and sa_member.holds(Permission.CASES_CLOSE):
        return sa_member, "super_admin"
    return None


def reopener_member(
    session: Session, user: User | Member, case: Case, closure: CaseClosure | None = None
) -> Member | None:
    """Decision 18: the first caller membership holding `cases.reopen` whose department is the owning department
    (the active primary owner, else the department named on the closure); else the super admin membership."""
    owner = primary_owner(session, case)
    office_id = owner.office_id if owner is not None else (closure.office_id if closure is not None else None)
    for m in access.holders_in(session, user, Permission.CASES_REOPEN):
        if office_id is not None and m.department is not None and m.department.id == office_id:
            return m
    sa_member = access.super_admin_member(session, user)
    if sa_member is not None and sa_member.holds(Permission.CASES_REOPEN):
        return sa_member
    return None


def close_flags(session: Session, user: User | Member, case: Case) -> dict[str, Any]:
    """Decision 20: `close` (every write check of decision 4 passes, the caller being able to open the case),
    `close_as`, and `close_blocked` — `not_disposed` / `transfer_open`, only when the caller holds `cases.close`
    and would be a closer but condition 6 or 7 fails. No lock, no write."""
    out: dict[str, Any] = {"close": False, "close_as": None, "close_blocked": None}
    if not access.has(session, user, Permission.CASES_CLOSE):
        return out
    owner = primary_owner(session, case)
    custody = session.get(Custody, case.id)
    if owner is None or custody is None or is_closed(session, case):
        return out
    found = closer_member(session, user, case, custody, owner)
    if found is None:
        return out
    if CaseStatus(case.status) != CaseStatus.DISPOSED:
        out["close_blocked"] = "not_disposed"
    elif _open_transfer(session, case):
        out["close_blocked"] = "transfer_open"
    else:
        out["close"], out["close_as"] = True, found[1]
    return out


def reopen_flags(session: Session, user: User | Member, case: Case) -> dict[str, Any]:
    """Decision 20: `reopen` (every check of decision 18 passes) and `reopen_blocked = "not_own_department"` when the
    case is closed and the caller holds `cases.reopen` but neither in the owning department nor as super admin."""
    out: dict[str, Any] = {"reopen": False, "reopen_blocked": None}
    closure = open_closure(session, case)
    if closure is None or not access.has(session, user, Permission.CASES_REOPEN):
        return out
    if reopener_member(session, user, case, closure) is None:
        out["reopen_blocked"] = "not_own_department"
    else:
        out["reopen"] = True
    return out


def brief(session: Session, user: User | Member, closure: CaseClosure | None) -> dict[str, Any] | None:
    """`CaseClosureOut`: the closure with the closer and the reopener; a remark's `ref_no` only when the caller may
    read that note (the note rule)."""
    if closure is None:
        return None
    office = session.get(Office, closure.office_id)
    note = session.get(CaseNote, closure.note_id)
    reopen_note = session.get(CaseNote, closure.reopen_note_id) if closure.reopen_note_id else None
    return {
        "closed_at": closure.closed_at,
        "closed_as": closure.closed_as,
        "closed_by": {
            "name": closure.actor_name,
            "designation": closure.actor_designation,
            "office_code": closure.actor_office_code,
        },
        "office_code": office.code if office is not None else None,
        "note_ref_no": note.ref_no
        if note is not None and visibility.can_view_note(session, user, note)
        else None,
        "disposal_date": closure.disposal_date,
        "reopened_at": closure.reopened_at,
        "reopen_kind": closure.reopen_kind,
        "reopened_status": CaseStatus(closure.reopened_status).value if closure.reopened_status else None,
        "reopened_by": (
            {
                "name": closure.reopened_by_name,
                "designation": closure.reopened_by_designation,
                "office_code": closure.reopened_by_office_code,
            }
            if closure.reopened_by_name
            else None
        ),
        "reopen_note_ref_no": (
            reopen_note.ref_no
            if reopen_note is not None and visibility.can_view_note(session, user, reopen_note)
            else None
        ),
    }


# ------------------------------------------------------------------------------------------------ closing


@dataclass
class CloseResult:
    closure: CaseClosure
    note: CaseNote
    leg: CustodyHistory
    finalised: list[str] = field(default_factory=list)


def _reread_case(session: Session, case: Case) -> Case:
    """The case row as it is now, under the lock already taken (a court apply may have changed the status)."""
    return session.execute(
        select(Case).where(Case.id == case.id).execution_options(populate_existing=True)
    ).scalar_one()


def close(
    session: Session, actor: Actor, user: User | Member, case: Case, *, remark: str | None
) -> CloseResult:
    """Decision 4's checks in order — visible (404) → remark (400) → `cases.close` (403 `function_missing`) → lock →
    claimed with custody (409 `not_owned`) → not closed (409 `already_closed`) → disposed (409 `not_disposed`) → no
    open transfer (409 `transfer_open`) → standing (403 `not_closer`) — then decision 6's writes."""
    from aslms.services import custody as custody_svc
    from aslms.services import notes

    require_visible_basis(session, user, case)
    text = clean_text(remark, "remark", min_len=REMARK_MIN, max_len=REMARK_MAX)
    if not access.has(session, user, Permission.CASES_CLOSE):
        raise forbidden("function_missing", "cases.close is not enabled for you")
    lock_case(session, case)
    case = _reread_case(session, case)
    owner = primary_owner(session, case)
    custody = session.get(Custody, case.id)
    if owner is None or custody is None:
        raise conflict("not_owned", MESSAGES["not_owned"])
    if open_closure(session, case, lock=True) is not None:
        raise conflict("already_closed", MESSAGES["already_closed"])
    if CaseStatus(case.status) != CaseStatus.DISPOSED:
        raise conflict("not_disposed", MESSAGES["not_disposed"])
    if _open_transfer(session, case):
        raise conflict("transfer_open", MESSAGES["transfer_open"])
    found = closer_member(session, user, case, custody, owner)
    if found is None:
        raise forbidden("not_closer", MESSAGES["not_closer"])
    member, closed_as = found
    actor = access.actor_as(actor, member)
    owner_office = session.get(Office, owner.office_id)
    before = custody_svc.card_summary(session, custody)
    leg = custody_svc.move_custody(
        session, actor, case, office=owner_office, reason="closed", pending_action=PendingAction.NONE
    )
    finalised = list(getattr(leg, "finalised_ref_nos", []))
    note = notes.add_system_kind_note(session, actor, member, case, custody, kind=NoteKind.CLOSING, body=text)
    closure = CaseClosure(
        case_id=case.id,
        office_id=owner_office.id,
        ownership_id=owner.id,
        closed_as=closed_as,
        note_id=note.id,
        close_leg_id=leg.id,
        disposal_date=case.disposal_date,
        **snapshot(actor),
    )
    try:
        with session.begin_nested():
            session.add(closure)
            session.flush()
    except IntegrityError as exc:
        raise conflict("concurrent_change", MESSAGES["concurrent_change"]) from exc
    emit_event(
        session,
        EventType.CASE_CLOSED,
        case,
        {
            "closure_id": str(closure.id),
            "office_code": owner_office.code,
            "closed_as": closed_as,
            "note_ref_no": note.ref_no,
            "seq_no": leg.seq_no,
        },
        dedupe=f"case_closed:{closure.id}",
        actor_user_id=actor.user_id,
    )
    write_audit(
        session,
        actor,
        "case.closed",
        "case_closure",
        closure.id,
        case_id=case.id,
        before=before,
        after={
            "closed_as": closed_as,
            "office_code": owner_office.code,
            "seq_no": leg.seq_no,
            "note_ref_no": note.ref_no,
            "remark": digest(text),
            "finalised_notes": finalised,
            "disposal_date": case.disposal_date,
        },
    )
    return CloseResult(closure, note, leg, finalised)


# ------------------------------------------------------------------------------------------------ reopening


@dataclass
class ReopenResult:
    closure: CaseClosure
    leg: CustodyHistory
    note: CaseNote | None = None


def _apply_reopen(
    session: Session,
    case: Case,
    closure: CaseClosure,
    *,
    kind: str,
    actor: Actor,
    member: Member | None = None,
    body: str | None = None,
    previous_status: CaseStatus | str | None = None,
) -> ReopenResult:
    """Decision 12, under the case row lock the caller took: the `reopened` leg (to the primary owner's office, or
    the closure's office if somehow none), for a manual reopen the `reopening` note, the closure's reopening columns,
    the `case_reopened` event and the `case.reopened` audit row."""
    from aslms.services import custody as custody_svc
    from aslms.services import notes

    owner = primary_owner(session, case)
    office = session.get(Office, owner.office_id if owner is not None else closure.office_id)
    status_now = CaseStatus(case.status)
    before_status = CaseStatus(previous_status) if previous_status is not None else status_now
    leg = custody_svc.move_custody(
        session, actor, case, office=office, reason="reopened", pending_action=PendingAction.EXAMINE
    )
    note = None
    if kind == "manual":
        custody = session.get(Custody, case.id)
        note = notes.add_system_kind_note(
            session, actor, member, case, custody, kind=NoteKind.REOPENING, body=body or ""
        )
    closure.reopened_at = _now()
    closure.reopen_kind = kind
    closure.reopen_leg_id = leg.id
    closure.reopened_status = status_now
    if note is not None:
        closure.reopen_note_id = note.id
        closure.reopened_by_user_id = actor.user_id
        closure.reopened_by_name = actor.name[:200]
        closure.reopened_by_designation = (actor.designation or None) and actor.designation[:200]
        closure.reopened_by_office_code = (actor.office_code or None) and actor.office_code[:40]
    session.flush()
    payload = {
        "closure_id": str(closure.id),
        "office_code": office.code,
        "reopen_kind": kind,
        "status": [before_status.value, status_now.value],
        "closed_at": closure.closed_at,
        "seq_no": leg.seq_no,
    }
    if note is not None:
        payload["note_ref_no"] = note.ref_no
    emit_event(
        session,
        EventType.CASE_REOPENED,
        case,
        payload,
        dedupe=f"case_reopened:{closure.id}",
        actor_user_id=actor.user_id,
    )
    after: dict[str, Any] = {
        "reopen_kind": kind,
        "closed_at": closure.closed_at,
        "status": status_now.value,
        "seq_no": leg.seq_no,
        "office_code": office.code,
    }
    if note is not None:
        after["note_ref_no"] = note.ref_no
        after["reason"] = digest(body)
    write_audit(session, actor, "case.reopened", "case_closure", closure.id, case_id=case.id, after=after)
    return ReopenResult(closure, leg, note)


def reopen(
    session: Session, actor: Actor, user: User | Member, case: Case, *, reason: str | None
) -> ReopenResult:
    """Decision 18's checks in order — visible (404) → reason (400) → `cases.reopen` (403 `function_missing`) → lock →
    an open closure (409 `not_closed`) → the owning department's membership or the super admin (403
    `not_reopener`) — then decision 12's writes. No court-status condition."""
    require_visible_basis(session, user, case)
    text = clean_text(reason, "reason", min_len=REMARK_MIN, max_len=REMARK_MAX)
    if not access.has(session, user, Permission.CASES_REOPEN):
        raise forbidden("function_missing", "cases.reopen is not enabled for you")
    lock_case(session, case)
    case = _reread_case(session, case)
    closure = open_closure(session, case, lock=True)
    if closure is None:
        raise conflict("not_closed", MESSAGES["not_closed"])
    member = reopener_member(session, user, case, closure)
    if member is None:
        raise forbidden("not_reopener", MESSAGES["not_reopener"])
    actor = access.actor_as(actor, member)
    return _apply_reopen(session, case, closure, kind="manual", actor=actor, member=member, body=text)


def reopen_on_court_status(
    session: Session, case: Case, *, previous_status: CaseStatus | str | None = None
) -> CaseClosure | None:
    """Decision 11: the court's status reads `pending` while a closure is open → the automatic reopen, with the
    system actor "court status". `unknown` never reopens. Idempotent: a second call finds no open closure."""
    if CaseStatus(case.status) != CaseStatus.PENDING or case.id is None:
        return None
    if not is_closed(session, case):
        return None
    lock_case(session, case)
    closure = open_closure(session, case, lock=True)
    if closure is None:
        return None
    result = _apply_reopen(
        session,
        case,
        closure,
        kind="automatic",
        actor=Actor.system(COURT_STATUS_ACTOR),
        previous_status=previous_status,
    )
    return result.closure
