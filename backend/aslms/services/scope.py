"""Visibility, enforced in SQL (ground rule 6; plan Table 1).

Two levels of access to a case:
  tracking card   case number, CNR, court, status, next hearing, owning department — every signed-in user
                  (so any department can find and claim a case from the unclaimed pool)
  contents        parties, hearings, orders, documents, notes, timeline — only within scope:
    state_oversight, auditor, central_operator    every case (read-only for the first two)
    dept_head, dept_admin                         cases owned or watched by their department (path prefix)
    directorate_user                              cases allotted to their directorate (unit) or its officers
    dept_officer, referral_reviewer               cases allotted to them or to their unit
    standing_counsel                              cases where a counsel code of their department appears

`case_scope_clause(user)` returns a SQL boolean over `Case`; every query that returns case contents is filtered
with it. `case_in_scope()` answers the same question for one case id, with the same SQL."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import and_, exists, false, or_, select, true
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement

from aslms.core.errors import ForbiddenError
from aslms.domain.cases import Case, CaseAdvocate
from aslms.domain.org import Office, Role, User
from aslms.domain.ownership import CaseOwnership, CounselCode, OwnershipStatus

STATE_TIER = frozenset({Role.STATE_OVERSIGHT, Role.AUDITOR, Role.CENTRAL_OPERATOR})
READ_ONLY = frozenset({Role.STATE_OVERSIGHT, Role.AUDITOR})
DEPT_WIDE = frozenset({Role.DEPT_HEAD, Role.DEPT_ADMIN})
INBOX_ROLES = frozenset({Role.DEPT_ADMIN, Role.DEPT_HEAD})
ADMIN_ROLES = frozenset({Role.CENTRAL_OPERATOR})  # State-wide administration
DEPT_ADMIN_ROLES = frozenset({Role.DEPT_ADMIN, Role.CENTRAL_OPERATOR})


@dataclass(frozen=True)
class Principal:
    """The signed-in user with the facts scope needs, loaded once per request."""

    user_id: uuid.UUID
    role: Role
    office_id: uuid.UUID
    office_path: str
    office_code: str
    department_id: uuid.UUID | None
    department_path: str
    department_code: str

    @property
    def is_state_tier(self) -> bool:
        return self.role in STATE_TIER

    @property
    def read_only(self) -> bool:
        return self.role in READ_ONLY


def principal_for(session: Session, user: User) -> Principal:
    office = session.get(Office, user.office_id)
    dept_path = office.path.split("/", 1)[0]
    dept = session.scalar(select(Office).where(Office.path == dept_path))
    return Principal(
        user.id,
        user.role,
        office.id,
        office.path,
        office.code,
        dept.id if dept else None,
        dept_path,
        dept.code if dept else office.code,
    )


def _under(path_col, path: str) -> ColumnElement[bool]:
    return or_(path_col == path, path_col.like(path + "/%"))


def case_scope_clause(p: Principal) -> ColumnElement[bool]:
    if p.is_state_tier:
        return true()
    owner_office = Office.__table__.alias("owner_office")
    unit_office = Office.__table__.alias("unit_office")
    active = and_(CaseOwnership.case_id == Case.id, CaseOwnership.status == OwnershipStatus.ACTIVE)
    if p.role in DEPT_WIDE:
        return exists(
            select(CaseOwnership.id)
            .join(owner_office, owner_office.c.id == CaseOwnership.office_id)
            .where(active, _under(owner_office.c.path, p.department_path))
        )
    if p.role == Role.DIRECTORATE_USER:
        officer_office = Office.__table__.alias("officer_office")
        return or_(
            exists(
                select(CaseOwnership.id)
                .join(unit_office, unit_office.c.id == CaseOwnership.unit_office_id)
                .where(active, _under(unit_office.c.path, p.office_path))
            ),
            exists(
                select(CaseOwnership.id)
                .join(User, User.id == CaseOwnership.officer_user_id)
                .join(officer_office, officer_office.c.id == User.office_id)
                .where(active, _under(officer_office.c.path, p.office_path))
            ),
        )
    if p.role in (Role.DEPT_OFFICER, Role.REFERRAL_REVIEWER):
        return or_(
            exists(select(CaseOwnership.id).where(active, CaseOwnership.officer_user_id == p.user_id)),
            exists(
                select(CaseOwnership.id)
                .join(unit_office, unit_office.c.id == CaseOwnership.unit_office_id)
                .where(active, _under(unit_office.c.path, p.office_path))
            ),
        )
    if p.role == Role.STANDING_COUNSEL:
        code_office = Office.__table__.alias("code_office")
        my_codes = (
            select(CounselCode.code)
            .join(code_office, code_office.c.id == CounselCode.office_id)
            .where(CounselCode.is_active.is_(True), _under(code_office.c.path, p.department_path))
        )
        return exists(
            select(CaseAdvocate.id).where(
                CaseAdvocate.case_id == Case.id, CaseAdvocate.counsel_code.in_(my_codes)
            )
        )
    return false()


def case_in_scope(session: Session, p: Principal, case_id: uuid.UUID) -> bool:
    return bool(session.scalar(select(Case.id).where(Case.id == case_id, case_scope_clause(p))))


def require_case_scope(session: Session, p: Principal, case_id: uuid.UUID) -> None:
    if not case_in_scope(session, p, case_id):
        raise ForbiddenError("this case is outside your access", case_id=str(case_id))


def require_role(p: Principal, *roles: Role) -> None:
    if p.role not in roles:
        raise ForbiddenError("your role cannot do this", role=p.role.value)


def require_write(p: Principal) -> None:
    if p.read_only:
        raise ForbiddenError("your role is read-only")


def acting_department(p: Principal, office_id: uuid.UUID | None = None) -> uuid.UUID:
    """The department a dept admin/head acts for. The central operator may act for any department."""
    if p.role == Role.CENTRAL_OPERATOR:
        if office_id is None:
            raise ForbiddenError("central operator must name the department (office_id)")
        return office_id
    if p.role not in INBOX_ROLES or p.department_id is None:
        raise ForbiddenError("only a department admin or head can act for the department")
    if office_id and office_id != p.department_id:
        raise ForbiddenError("you can act only for your own department")
    return p.department_id


def can_admin_office(session: Session, p: Principal, office_id: uuid.UUID) -> bool:
    if p.role == Role.CENTRAL_OPERATOR:
        return True
    if p.role != Role.DEPT_ADMIN:
        return False
    office = session.get(Office, office_id)
    return bool(
        office and (office.path == p.department_path or office.path.startswith(p.department_path + "/"))
    )
