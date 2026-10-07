"""Custody, minimal (design `recommend-and-claim`, decision 11): custody follows primary ownership only, so
that alerts find a holder before `custody-workflow` adds requests and hand-overs on the same function.

Reasons written now: `claimed` (the department), `allotted` (the unit if set, else the department; the officer
as holder user), `taken_over` (the new unit, else the department; the taker), `transferred` (the target
department). `reassigned_on_exit` (design `user-memberships`, decision 21): a file held by a membership that
leaves the department goes to the officer the admin chose, with its pending action and due date carried over
or changed. The caller holds the case row lock."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aslms.domain.cases import Case
from aslms.domain.org import Office, User
from aslms.domain.reference import EventType
from aslms.domain.workflow import Custody, CustodyHistory, PendingAction
from aslms.services.audit import Actor, snapshot
from aslms.services.cases import emit_event

REASONS = frozenset({"claimed", "allotted", "taken_over", "transferred", "reassigned_on_exit"})


def move_custody(
    session: Session,
    actor: Actor,
    case: Case,
    *,
    office: Office,
    user: User | None = None,
    reason: str,
    pending_action: PendingAction = PendingAction.NONE,
    due_date: date | None = None,
    extra: dict[str, Any] | None = None,
) -> CustodyHistory:
    if reason not in REASONS:
        raise ValueError(f"unknown custody reason {reason!r}")
    now = datetime.now(UTC)
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
        reason=reason,
        pending_action=pending_action,
        due_date=due_date,
        started_at=now,
        **snapshot(actor),
    )
    session.add(leg)
    session.flush()
    row = session.get(Custody, case.id)
    if row is None:
        row = Custody(case_id=case.id, holder_office_id=office.id)
        session.add(row)
    row.holder_office_id = office.id
    row.holder_user_id = user.id if user else None
    row.pending_action = pending_action
    row.since = now
    row.due_date = due_date
    row.current_leg_id = leg.id
    session.flush()
    emit_event(
        session,
        EventType.CUSTODY_MOVED,
        case,
        {
            "office_code": office.code,
            "user_id": str(user.id) if user else None,
            "user_name": user.full_name if user else None,
            "reason": reason,
            "seq_no": leg.seq_no,
            **(extra or {}),
        },
        dedupe=f"custody_moved:{case.id}:{leg.seq_no}",
        actor_user_id=actor.user_id,
    )
    return leg
