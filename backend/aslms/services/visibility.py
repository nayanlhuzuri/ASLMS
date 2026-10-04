"""Case visibility by ownership (design `recommend-and-claim`, decisions 15, 16, 23). `cases-api` extends these
predicates (custody, requests, counsel) instead of re-deriving ownership scope.

- `department_of(session, office)`: the Department-tier ancestor of an office (the second segment of
  `offices.path`), or None for the State root.
- `claimed_conditions(...)`: the Claimed-tab predicate over `case_ownership` joined to `cases`: the whole
  department for callers holding `cases.claim` or `cases.allot` (or reading another office with
  `cases.view_all`); otherwise the rows allotted to the caller, or to a unit in the caller's subtree when the
  caller sits below the department.
- `owned_case_filter(session, user)`: the same predicate as a filter on `cases.id`."""

from __future__ import annotations

from typing import Literal

from sqlalchemy import false, or_, select
from sqlalchemy.orm import Session

from aslms.domain.cases import Case, CaseStatus
from aslms.domain.org import Office, User
from aslms.domain.ownership import CaseOwnership, OwnershipStatus
from aslms.domain.reference import OfficeKind, Permission
from aslms.services import access

DEPARTMENT_TIER_KINDS = frozenset({OfficeKind.DEPARTMENT, OfficeKind.CENTRAL, OfficeKind.ADVOCATE_GENERAL})
CaseState = Literal["active", "disposed", "all"]


def is_department(office: Office | None) -> bool:
    return (
        office is not None
        and office.path.count("/") == 1
        and OfficeKind(office.kind) in DEPARTMENT_TIER_KINDS
    )


def department_of(session: Session, office: Office | None) -> Office | None:
    if office is None:
        return None
    parts = office.path.split("/")
    if len(parts) < 2:
        return None
    dept = office if len(parts) == 2 else session.scalar(select(Office).where(Office.code == parts[1]))
    return dept if is_department(dept) else None


def user_department(session: Session, user: User) -> Office | None:
    return department_of(session, session.get(Office, user.office_id))


def in_subtree(office: Office, root: Office) -> bool:
    return office.id == root.id or office.path.startswith(root.path + "/")


def case_state_condition(case_state: CaseState):
    if case_state == "active":
        return Case.status.in_([CaseStatus.PENDING, CaseStatus.UNKNOWN])
    if case_state == "disposed":
        return Case.status == CaseStatus.DISPOSED
    return None


def whole_department(session: Session, user: User) -> bool:
    return access.has(session, user, Permission.CASES_CLAIM) or access.has(
        session, user, Permission.CASES_ALLOT
    )


def claimed_conditions(
    session: Session,
    user: User,
    department: Office,
    *,
    case_state: CaseState = "active",
    whole: bool | None = None,
) -> list:
    """Conditions over `CaseOwnership` (and `Case`, which the caller joins) for the department's active
    ownership rows the user may see in the Claimed tab."""
    conds = [CaseOwnership.office_id == department.id, CaseOwnership.status == OwnershipStatus.ACTIVE]
    if whole is None:
        whole = whole_department(session, user)
    if not whole:
        own = session.get(Office, user.office_id)
        if own is None or not in_subtree(own, department):
            return [false()]
        if own.id == department.id:
            conds.append(CaseOwnership.officer_user_id == user.id)
        else:
            units = select(Office.id).where(or_(Office.id == own.id, Office.path.like(own.path + "/%")))
            conds.append(
                or_(CaseOwnership.officer_user_id == user.id, CaseOwnership.unit_office_id.in_(units))
            )
    state = case_state_condition(case_state)
    if state is not None:
        conds.append(state)
    return conds


def owned_case_filter(session: Session, user: User, *, case_state: CaseState = "active"):
    """A filter on `Case.id`: the cases of the user's own department that the user may see by ownership."""
    dept = user_department(session, user)
    if dept is None:
        return false()
    sub = (
        select(CaseOwnership.case_id)
        .join(Case, Case.id == CaseOwnership.case_id)
        .where(*claimed_conditions(session, user, dept, case_state=case_state))
    )
    return Case.id.in_(sub)
