"""User types, functions and delegation against the test database: the seeded matrix, effective functions
(type + grants − denies, super admin, inactive), who may create or change whom, and the audit rows."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from aslms.domain.events import AuditLog, Event
from aslms.domain.org import Office, PermissionEffect, RolePermission, User
from aslms.domain.reference import OfficeKind, Permission, Role
from aslms.services import access
from aslms.services.access import Forbidden
from aslms.services.access_seed import DEFAULT_MATRIX
from aslms.services.audit import Actor
from aslms.services.seed import seed_all
from aslms.services.users import UserError, authenticate, create_user
from tests.db.conftest import wipe

SYS = Actor.system("test")


def _office(s, code, name, kind, parent=None):
    o = Office(
        code=code,
        name=name,
        kind=kind,
        parent_id=parent.id if parent else None,
        path=f"{parent.path}/{code}" if parent else code,
    )
    s.add(o)
    s.flush()
    return o


@pytest.fixture()
def world(session):
    """GOA (state) > EDU (department) > EDU-DSE (directorate), HEALTH; a super admin, a dept admin of EDU."""
    wipe(session)
    seed_all(session)
    goa = session.scalar(sa.select(Office).where(Office.code == "GOA"))
    edu = _office(session, "EDU", "Education", OfficeKind.DEPARTMENT, goa)
    dse = _office(session, "EDU-DSE", "Directorate of Secondary Education", OfficeKind.DIRECTORATE, edu)
    health = _office(session, "HEALTH", "Health", OfficeKind.DEPARTMENT, goa)
    sa_user = create_user(
        session,
        SYS,
        email="root@example.org",
        password="correct-horse-battery",
        full_name="Root",
        role=Role.SUPER_ADMIN,
        office=goa,
    )
    admin = create_user(
        session,
        SYS,
        email="admin.edu@example.org",
        password="correct-horse-battery",
        full_name="EDU Admin",
        role=Role.DEPT_ADMIN,
        office=edu,
    )
    return {"goa": goa, "edu": edu, "dse": dse, "health": health, "super": sa_user, "admin": admin}


def test_seed_builds_the_full_matrix(session):
    wipe(session)
    seed_all(session)
    n = session.scalar(sa.select(sa.func.count()).select_from(RolePermission))
    assert n == len(DEFAULT_MATRIX) * len(Permission) == 9 * 49
    assert session.scalar(sa.text("select count(*) from ref_permission")) == 49
    # custody-workflow decision 22: the two request functions are retired, 47 stay active
    assert session.scalar(sa.text("select count(*) from ref_permission where is_active")) == 47
    assert session.scalar(sa.text("select count(*) from ref_role")) == 10
    m = access.matrix(session)
    assert m["dept_admin"]["users.create"] and not m["dept_officer"]["users.create"]
    assert m["auditor"]["audit.view"] and not m["dept_admin"]["audit.view"]
    assert all(v for k, v in m["super_admin"].items() if not k.startswith("requests."))
    assert not m["super_admin"]["requests.send"] and not m["dept_admin"]["requests.answer"]
    seed_all(session)  # idempotent
    assert session.scalar(sa.select(sa.func.count()).select_from(RolePermission)) == n


def test_effective_functions(session, world):
    sup, admin, edu = world["super"], world["admin"], world["edu"]
    assert access.effective_permissions(session, sup) == set(access.ACTIVE_FUNCTIONS)
    assert Permission.REQUESTS_SEND not in access.effective_permissions(session, sup)
    perms = access.effective_permissions(session, admin)
    assert Permission.USERS_CREATE in perms and Permission.ACCESS_MANAGE_TYPES not in perms
    officer = create_user(
        session,
        SYS,
        email="off@example.org",
        password="correct-horse-battery",
        full_name="Officer",
        role=Role.DEPT_OFFICER,
        office=edu,
    )
    base = access.effective_permissions(session, officer)
    assert Permission.NOTES_ADD in base and Permission.CASES_CLAIM not in base
    sup_actor = access.actor_for(sup, world["goa"])
    access.set_override(
        session,
        sup_actor,
        sup,
        officer,
        Permission.CASES_CLAIM,
        PermissionEffect.GRANT,
        reason="acting admin",
    )
    access.set_override(session, sup_actor, sup, officer, Permission.NOTES_ADD, PermissionEffect.DENY)
    now = access.effective_permissions(session, officer)
    assert Permission.CASES_CLAIM in now and Permission.NOTES_ADD not in now
    access.set_override(session, sup_actor, sup, officer, Permission.NOTES_ADD, None)
    assert Permission.NOTES_ADD in access.effective_permissions(session, officer)
    # the type matrix switch reaches every user of the type
    access.set_matrix(session, sup_actor, sup, Role.DEPT_OFFICER, Permission.DOCUMENTS_UPLOAD, False)
    assert Permission.DOCUMENTS_UPLOAD not in access.effective_permissions(session, officer)
    # disabled → nothing; a super admin cannot be denied
    access.set_enabled(session, sup_actor, sup, officer, False)
    assert access.effective_permissions(session, officer) == set()
    with pytest.raises(Forbidden):
        access.set_override(session, sup_actor, sup, sup, Permission.AUDIT_VIEW, PermissionEffect.DENY)
    with pytest.raises(Forbidden):
        access.set_enabled(session, sup_actor, sup, sup, False)
    audits = session.scalars(sa.select(AuditLog.action).order_by(AuditLog.created_at, AuditLog.id)).all()
    assert audits.count("access.override") == 3 and "access.matrix" in audits and "user.disable" in audits
    assert (
        session.scalar(sa.select(sa.func.count()).select_from(Event).where(Event.type == "access_changed"))
        == 4
    )


def test_delegation_rules(session, world):
    admin, edu, dse, health = world["admin"], world["edu"], world["dse"], world["health"]
    actor = access.actor_for(admin, edu)
    # inside the subtree, a delegable type: allowed
    access.assert_can_manage(session, admin, "create", target_office=dse, target_role=Role.DIRECTORATE_USER)
    officer = create_user(
        session,
        actor,
        email="dse@example.org",
        password="correct-horse-battery",
        full_name="DSE User",
        role=Role.DIRECTORATE_USER,
        office=dse,
    )
    # outside the subtree
    with pytest.raises(Forbidden, match="outside"):
        access.assert_can_manage(
            session, admin, "create", target_office=health, target_role=Role.DEPT_OFFICER
        )
    # a type only the super admin may create
    with pytest.raises(Forbidden, match="super admin"):
        access.assert_can_manage(session, admin, "create", target_office=edu, target_role=Role.DEPT_ADMIN)
    # a function the admin does not hold
    with pytest.raises(Forbidden, match="do not hold"):
        access.set_override(
            session, actor, admin, officer, Permission.ACCESS_MANAGE_TYPES, PermissionEffect.GRANT
        )
    # a function the admin holds: fine, and audited with the admin as actor
    row = access.set_override(session, actor, admin, officer, Permission.CASES_CLAIM, PermissionEffect.GRANT)
    assert row.granted_by_user_id == admin.id and row.actor_office_code == "EDU"
    # the matrix is the super admin's alone
    with pytest.raises(Forbidden):
        access.set_matrix(session, actor, admin, Role.DEPT_OFFICER, Permission.NOTES_ADD, False)
    # a dept admin may not change types to or from non-delegable ones
    with pytest.raises(Forbidden):
        access.set_type(session, actor, admin, officer, Role.DEPT_HEAD)
    access.set_type(session, actor, admin, officer, Role.DEPT_OFFICER)
    assert officer.role == Role.DEPT_OFFICER


def test_create_user_validation_and_login(session, world):
    edu = world["edu"]
    with pytest.raises(UserError):
        create_user(
            session,
            SYS,
            email="not-an-email",
            password="correct-horse-battery",
            full_name="x",
            role=Role.DEPT_OFFICER,
            office=edu,
        )
    with pytest.raises(UserError):
        create_user(
            session,
            SYS,
            email="short@example.org",
            password="short",
            full_name="x",
            role=Role.DEPT_OFFICER,
            office=edu,
        )
    with pytest.raises(UserError):
        create_user(
            session,
            SYS,
            email="ADMIN.EDU@example.org",
            password="correct-horse-battery",
            full_name="dup",
            role=Role.DEPT_OFFICER,
            office=edu,
        )
    assert authenticate(session, "Admin.EDU@example.org", "correct-horse-battery") is not None
    assert authenticate(session, "admin.edu@example.org", "wrong-password-xx") is None
    assert authenticate(session, "nobody@example.org", "correct-horse-battery") is None
    admin = world["admin"]
    assert admin.last_login_at is not None
    sup_actor = access.actor_for(world["super"], world["goa"])
    access.set_enabled(session, sup_actor, world["super"], admin, False)
    assert authenticate(session, "admin.edu@example.org", "correct-horse-battery") is None
    assert session.scalar(sa.select(sa.func.count()).select_from(User)) == 2
    assert (
        session.scalar(sa.select(sa.func.count()).select_from(Event).where(Event.type == "user_created")) == 2
    )
