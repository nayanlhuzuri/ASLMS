"""What the custody, stage and note services share (design `custody-workflow`): the error type with its machine
code and HTTP status, the case row lock (decision 26), the "claimed case" rule (decision 1), the acting
membership of a case write (`user-memberships` decision 6), text and due-date checks, and the audit digest of a
text (decision 21: a length and a SHA-256, never the text)."""

from __future__ import annotations

import hashlib
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aslms.domain.cases import Case
from aslms.domain.org import User
from aslms.domain.ownership import CaseOwnership, OwnershipRole, OwnershipStatus
from aslms.domain.reference import Permission
from aslms.domain.workflow import PendingAction, ResponseMode
from aslms.services import access
from aslms.services.access import Member
from aslms.services.refno import now_ist
from aslms.services.visibility import WORKING_BASES, NotVisibleCase, access_basis, acting_member_for_case

MAX_DUE_DAYS = 365
REMARK_MIN, REMARK_MAX = 3, 2_000
STAGE_NOTE_MAX = 2_000

RESPONSE_MODE_LABELS = {
    ResponseMode.DEPARTMENT: "By the department",
    ResponseMode.COUNSEL: "By counsel",
    ResponseMode.NONE: "No response",
}


class WorkflowError(ValueError):
    """A refused workflow action. `code` is machine-readable; `http_status` 400, 403 or 409."""

    def __init__(self, code: str, message: str, http_status: int = 400):
        super().__init__(message)
        self.code = code
        self.http_status = http_status


def bad(message: str, code: str = "bad_field") -> WorkflowError:
    return WorkflowError(code, message, 400)


def forbidden(code: str, message: str) -> WorkflowError:
    return WorkflowError(code, message, 403)


def conflict(code: str, message: str) -> WorkflowError:
    return WorkflowError(code, message, 409)


def value(v: Any) -> Any:
    return v.value if hasattr(v, "value") and not isinstance(v, bool | int | float | str) else v


def today_ist() -> date:
    return now_ist().date()


def lock_case(session: Session, case: Case) -> None:
    """Decision 26: the case row lock, taken before custody, `seq_no` or the holder are read."""
    session.execute(select(Case.id).where(Case.id == case.id).with_for_update())


def primary_owner(session: Session, case: Case) -> CaseOwnership | None:
    return session.scalar(
        select(CaseOwnership).where(
            CaseOwnership.case_id == case.id,
            CaseOwnership.status == OwnershipStatus.ACTIVE,
            CaseOwnership.role == OwnershipRole.PRIMARY,
        )
    )


def require_owned(session: Session, case: Case) -> CaseOwnership:
    """Decision 1: custody, stages and notes exist only for a claimed case."""
    row = primary_owner(session, case)
    if row is None:
        raise conflict("not_owned", "the case has not been claimed by a department")
    return row


def require_visible_basis(session: Session, user: User | Member, case: Case) -> list[str]:
    bases = access_basis(session, user, case)
    if not bases:
        raise NotVisibleCase("no such case")
    return bases


def acting_member(session: Session, user: User | Member, case: Case, permission: Permission) -> Member:
    """The membership that writes on the case (`user-memberships` decision 6): a working basis and the function
    in the same membership; 403 `not_working_on_case` without a working basis, 403 `forbidden` without the
    function there."""
    member = acting_member_for_case(session, user, case, permission)
    if member is not None:
        return member
    bases = set(access_basis(session, user, case))
    if not WORKING_BASES & bases:
        raise forbidden("not_working_on_case", "your office does not own, hold or appear in this case")
    raise forbidden("forbidden", f"{permission.value} is not enabled for you on this case")


def require_function(session: Session, user: User | Member, permission: Permission) -> None:
    if not access.has(session, user, permission):
        raise forbidden("forbidden", f"{permission.value} is not enabled for you")


def clean_text(
    text: str | None, name: str, *, min_len: int, max_len: int, required: bool = True
) -> str | None:
    s = (text or "").strip()
    if not s:
        if required:
            raise bad(f"{name} is required")
        return None
    if not min_len <= len(s) <= max_len:
        raise bad(f"{name} must be {min_len} to {max_len} characters")
    return s


def check_due(due: date | None, *, today: date | None = None) -> date | None:
    """Decision 3: today (IST) or later, at most 365 days ahead (400 `bad_due_date`)."""
    if due is None:
        return None
    today = today or today_ist()
    if due < today:
        raise bad("due_date cannot be in the past", "bad_due_date")
    if due > today + timedelta(days=MAX_DUE_DAYS):
        raise bad(f"due_date is at most {MAX_DUE_DAYS} days ahead", "bad_due_date")
    return due


def pending_action(raw: str | PendingAction | None) -> PendingAction:
    """Decision 10: a send needs a pending action other than `none`."""
    if raw is None or str(value(raw)).strip() == "":
        raise bad("pending_action is required")
    try:
        action = PendingAction(str(value(raw)).strip().lower())
    except ValueError as exc:
        raise bad(f"unknown pending_action {raw!r}") from exc
    if action == PendingAction.NONE:
        raise bad("pending_action cannot be none when the file is sent")
    return action


def digest(text: str | None) -> dict[str, Any]:
    """Decision 21: what an audit row may say about a text."""
    data = (text or "").encode("utf-8")
    return {"length": len(text or ""), "sha256": hashlib.sha256(data).hexdigest()}
