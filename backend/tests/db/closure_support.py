"""Shared helpers for the Close Case tests (design `close-case`) over `tests/db/world.py` and
`tests/db/workflow_support.py`: a claimed EDU case the court has disposed of, a further login with one membership
(the HEALTH head), a function granted or denied to one membership, a watching department, and closing and reopening
through the service."""

from __future__ import annotations

from datetime import UTC, date, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aslms.domain.cases import Case, CaseStatus  # noqa: F401  (re-exported for the API tests)
from aslms.domain.org import PermissionEffect, User
from aslms.domain.ownership import CaseOwnership, OwnershipRole, OwnershipStatus
from aslms.domain.reference import Permission, Role
from aslms.domain.workflow import CaseClosure
from aslms.services import access, case_closure, memberships
from aslms.services.audit import Actor
from aslms.services.users import hash_password
from tests.db import workflow_support as w
from tests.db.world import PW, World

DISPOSED_ON = date(2026, 10, 20)
REMARK = "Disposed by the court; compliance reported and nothing more to do."


def disposed_case(s: Session, world: World, *, officer: str | None = "edu_off1") -> Case:
    """An EDU case claimed by the EDU admin, assigned to `officer`, then disposed of by the court."""
    case = w.claimed_case(s, world, officer=officer)
    case.status = CaseStatus.DISPOSED
    case.disposal_date = DISPOSED_ON
    s.flush()
    return case


def add_login(
    s: Session, world: World, key: str, role: Role, office_code: str, designation: str | None = None
):
    """A further login with one membership (tests only; no authority check)."""
    office = world.office(s, office_code)
    u = User(
        email=f"{key}@example.org",
        password_hash=hash_password(PW),
        full_name=key.replace("_", " ").title(),
        role=role,
        office_id=office.id,
    )
    s.add(u)
    s.flush()
    memberships.insert_membership(
        s, Actor.system("test"), u, office=office, role=role, designation=designation, audit=False
    )
    world.users[key] = u
    return u


def set_function(
    s: Session,
    world: World,
    key: str,
    permission: Permission,
    effect: PermissionEffect,
    office: str | None = None,
) -> None:
    actor, root = world.actor(s, "root")
    access.set_override(s, actor, root, world.membership(s, key, office), permission, effect)
    s.flush()


def watch(s: Session, world: World, case: Case, office_code: str) -> CaseOwnership:
    row = CaseOwnership(
        case_id=case.id,
        office_id=world.office(s, office_code).id,
        role=OwnershipRole.WATCHER,
        status=OwnershipStatus.ACTIVE,
        claimed_at=datetime.now(UTC),
    )
    s.add(row)
    s.flush()
    return row


def close(s: Session, world: World, key: str, case: Case, remark: str = REMARK):
    actor, user = world.actor(s, key)
    return case_closure.close(s, actor, user, case, remark=remark)


def reopen(
    s: Session, world: World, key: str, case: Case, reason: str = "The court's order needs compliance again."
):
    actor, user = world.actor(s, key)
    return case_closure.reopen(s, actor, user, case, reason=reason)


def closures(s: Session, case: Case) -> list[CaseClosure]:
    return list(
        s.scalars(
            sa.select(CaseClosure)
            .where(CaseClosure.case_id == case.id)
            .order_by(CaseClosure.closed_at, CaseClosure.id)
            .execution_options(populate_existing=True)
        ).all()
    )
