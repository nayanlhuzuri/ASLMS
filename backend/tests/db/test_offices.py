"""Offices administration against the test database: creation and placement, immutability, deactivation
refused while in use, delegation to a department admin, the first department admins, designations, and
the audit rows and events each write leaves."""

from __future__ import annotations

from datetime import date

import pytest
import sqlalchemy as sa

from aslms.domain.cases import FirstSeenSource
from aslms.domain.courts import Court
from aslms.domain.events import AuditLog, Event
from aslms.domain.org import Designation, Office, PermissionEffect, RolePermission
from aslms.domain.ownership import CaseOwnership, OwnershipStatus
from aslms.domain.reference import OfficeKind, Permission, Role
from aslms.domain.workflow import Custody
from aslms.services import access, memberships, offices, tickets
from aslms.services.access import Forbidden
from aslms.services.access_seed import DEFAULT_MATRIX
from aslms.services.audit import Actor
from aslms.services.cases import get_or_create_case
from aslms.services.offices import AdminExists, DuplicateCode, OfficeError, OfficeInUse
from aslms.services.seed import seed_all
from aslms.services.users import create_user
from tests.db.conftest import wipe

SYS = Actor.system("test")
PW = "correct-horse-battery-7"


def head(code: str) -> dict:
    """A new login as the head of a department being created (design `user-memberships`, decision 24)."""
    return {
        "email": f"head.{code.lower()}@example.org",
        "full_name": f"Head {code}",
        "designation": "Commissioner & Secretary",
        "password": PW,
    }


def end_head(session, sup, dept) -> None:
    """The super admin ends the department's head (exit with nothing held), leaving it headless."""
    current = memberships.head_of(session, dept)
    fp = memberships.fingerprint(memberships.exit_items(session, current))
    tickets.request_head_change(
        session,
        access.actor_for(sup),
        sup,
        {
            "operation": "end",
            "department_code": dept.code,
            "outgoing": {
                "mode": "exit",
                "assignments": [],
                "items_fingerprint": fp,
                "reason": "post abolished",
            },
        },
    )


@pytest.fixture()
def world(session):
    """GOA (seeded root); a super admin in GOA; EDU and HEALTH (departments, each created with its head); a
    dept admin of EDU."""
    wipe(session)
    seed_all(session)
    goa = session.scalar(sa.select(Office).where(Office.code == "GOA"))
    sup = create_user(
        session,
        SYS,
        email="root@example.org",
        password=PW,
        full_name="Root",
        role=Role.SUPER_ADMIN,
        office=goa,
    )
    sup_actor = access.actor_for(sup, goa)
    edu = offices.create_office(
        session, sup_actor, sup, code="edu", name="Education", kind="department", parent=goa, head=head("EDU")
    )
    health = offices.create_office(
        session,
        sup_actor,
        sup,
        code="HEALTH",
        name="Health",
        kind=OfficeKind.DEPARTMENT,
        parent=goa,
        head=head("HEALTH"),
    )
    admin = create_user(
        session,
        SYS,
        email="admin.edu@example.org",
        password=PW,
        full_name="EDU Admin",
        role=Role.DEPT_ADMIN,
        office=edu,
    )
    return {
        "goa": goa,
        "edu": edu,
        "health": health,
        "super": sup,
        "sup_actor": sup_actor,
        "admin": admin,
        "admin_actor": access.actor_for(admin, edu),
    }


def audits(session, action: str, entity_id=None) -> list[AuditLog]:
    stmt = sa.select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.created_at, AuditLog.id)
    if entity_id is not None:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    return list(session.scalars(stmt).all())


def events(session, action: str) -> list[Event]:
    return list(
        session.scalars(
            sa.select(Event).where(Event.type == "config_changed", Event.payload["action"].astext == action)
        ).all()
    )


# ------------------------------------------------------------------------------------------------ creation


def test_super_admin_creates_a_department(session, world):
    edu, sup = world["edu"], world["super"]
    assert edu.path == "GOA/EDU" and edu.code == "EDU" and edu.kind == OfficeKind.DEPARTMENT
    db_today = session.scalar(
        sa.select(sa.func.current_date())
    )  # `valid_from` is the database's current_date
    assert edu.created_by == sup.id and edu.valid_from == db_today and edu.is_active
    assert offices.tier_of(edu) == "department"
    rows = audits(session, "office.create", edu.id)
    assert len(rows) == 1 and rows[0].after["path"] == "GOA/EDU" and rows[0].actor_user_id == sup.id
    assert len(events(session, "create")) == 2  # EDU and HEALTH
    assert events(session, "create")[0].payload["entity"] == "office"


def test_placement_rules(session, world):
    goa, edu, sup, actor = world["goa"], world["edu"], world["super"], world["sup_actor"]
    dse = offices.create_office(
        session, actor, sup, code="EDU-DSE", name="Secondary Education", kind="directorate", parent=edu
    )
    assert dse.path == "GOA/EDU/EDU-DSE" and offices.tier_of(dse) == "directorate"
    unit = offices.create_office(
        session, actor, sup, code="EDU-DSE-LEGAL", name="Legal cell", kind="unit", parent=dse
    )
    assert unit.path == "GOA/EDU/EDU-DSE/EDU-DSE-LEGAL" and offices.tier_of(unit) == "directorate"
    with pytest.raises(OfficeError, match="cannot be placed"):
        offices.create_office(session, actor, sup, code="X1", name="x", kind="directorate", parent=goa)
    with pytest.raises(OfficeError, match="cannot be placed"):
        offices.create_office(session, actor, sup, code="X2", name="x", kind="department", parent=edu)
    with pytest.raises(OfficeError, match="seeded root"):
        offices.create_office(session, actor, sup, code="X3", name="x", kind="state", parent=goa)
    with pytest.raises(OfficeError, match="unknown office kind"):
        offices.create_office(session, actor, sup, code="X4", name="x", kind="ministry", parent=goa)
    with pytest.raises(OfficeError, match="name is required"):
        offices.create_office(session, actor, sup, code="X5", name="  ", kind="department", parent=goa)
    # a child under an inactive parent is refused
    offices.deactivate_office(session, actor, sup, unit)
    offices.deactivate_office(session, actor, sup, dse)
    with pytest.raises(OfficeError, match="inactive"):
        offices.create_office(session, actor, sup, code="X6", name="x", kind="unit", parent=dse)


def test_duplicate_code_is_refused_before_the_database(session, world):
    sup, actor, goa = world["super"], world["sup_actor"], world["goa"]
    for code in ("EDU", "edu", " Edu "):
        with pytest.raises(DuplicateCode):
            offices.create_office(session, actor, sup, code=code, name="again", kind="department", parent=goa)
    assert len(audits(session, "office.create")) == 2


def test_update_changes_only_name_notes_and_valid_from(session, world):
    edu, sup, actor = world["edu"], world["super"], world["sup_actor"]
    established = date(2010, 4, 1)
    offices.update_office(
        session, actor, sup, edu, name="Education Department", notes="Dispur", valid_from=established
    )
    assert edu.name == "Education Department" and edu.notes == "Dispur" and edu.valid_from == established
    assert edu.code == "EDU" and edu.kind == OfficeKind.DEPARTMENT and edu.path == "GOA/EDU"
    assert edu.parent_id == world["goa"].id and edu.updated_by == sup.id
    row = audits(session, "office.update", edu.id)[0]
    assert row.after == {"name": "Education Department", "notes": "Dispur", "valid_from": "2010-04-01"}
    assert row.before["name"] == "Education"
    assert len(events(session, "update")) == 1
    # nothing set → nothing written
    offices.update_office(session, actor, sup, edu)
    assert len(audits(session, "office.update", edu.id)) == 1
    # clearing the notes
    offices.update_office(session, actor, sup, edu, notes="")
    assert edu.notes is None


# ------------------------------------------------------------------------------------------------ deactivation


def test_deactivation_is_refused_while_in_use(session, world):
    goa, edu, admin, sup, actor = (
        world["goa"],
        world["edu"],
        world["admin"],
        world["super"],
        world["sup_actor"],
    )
    dse = offices.create_office(
        session, actor, sup, code="EDU-DSE", name="DSE", kind="directorate", parent=edu
    )
    court = session.scalar(sa.select(Court).where(Court.est_code == "GAHC01"))
    case, _ = get_or_create_case(
        session, court, cnr=None, case_no="WP(C)/1/2026", source=FirstSeenSource.SEARCH
    )
    own = CaseOwnership(case_id=case.id, office_id=edu.id, actor_name="test")
    session.add(own)
    session.add(Custody(case_id=case.id, holder_office_id=edu.id))
    session.flush()
    with pytest.raises(OfficeInUse) as exc:
        offices.deactivate_office(session, actor, sup, edu)
    # the users count is the office's active memberships: the admin and the head
    assert exc.value.counts == {"children": 1, "users": 2, "ownership": 1, "custody": 1}
    assert edu.is_active and not audits(session, "office.deactivate")
    # remove each dependency in turn: a disabled login still holds its membership
    offices.deactivate_office(session, actor, sup, dse)
    access.set_enabled(session, actor, sup, admin, False)
    assert offices.dependents(session, edu)["users"] == 2
    admin_m = memberships.admin_of(session, edu)
    memberships.end(
        session, actor, sup, admin_m, reason="post abolished", assignments=[], items_fingerprint=None
    )
    end_head(session, sup, edu)
    own.status = OwnershipStatus.TRANSFERRED  # a primary row is never released (recommend-and-claim)
    session.flush()
    with pytest.raises(OfficeInUse) as exc:
        offices.deactivate_office(session, actor, sup, edu)
    assert exc.value.counts == {"children": 0, "users": 0, "ownership": 0, "custody": 1}
    session.get(Custody, case.id).holder_office_id = world["health"].id  # moved, never deleted
    session.flush()
    offices.deactivate_office(session, actor, sup, edu)
    assert not edu.is_active and edu.deactivated_at is not None and edu.valid_to == date.today()
    assert session.get(Office, edu.id) is not None  # never deleted
    row = audits(session, "office.deactivate", edu.id)[0]
    assert row.before["is_active"] is True and row.after["is_active"] is False
    assert len(events(session, "deactivate")) == 2
    with pytest.raises(OfficeError, match="already inactive"):
        offices.deactivate_office(session, actor, sup, edu)
    # reactivation: the child fails under an inactive parent, succeeds once the parent is back
    with pytest.raises(OfficeError, match="parent office is inactive"):
        offices.reactivate_office(session, actor, sup, dse)
    with pytest.raises(offices.HeadRequired):
        offices.reactivate_office(session, actor, sup, edu)
    offices.reactivate_office(session, actor, sup, edu, head={"email": "head.edu@example.org"})
    assert memberships.head_of(session, edu) is not None
    assert edu.is_active and edu.deactivated_at is None and edu.valid_to is None
    offices.reactivate_office(session, actor, sup, dse)
    assert dse.is_active
    assert len(audits(session, "office.reactivate")) == 2 and len(events(session, "reactivate")) == 2
    with pytest.raises(OfficeError, match="already active"):
        offices.reactivate_office(session, actor, sup, dse)
    # the root and the actor's own office are never deactivated
    with pytest.raises(OfficeError, match="root"):
        offices.deactivate_office(session, actor, sup, goa)
    # someone holding offices.manage cannot deactivate the office they sit in (one super admin only, so a
    # directorate user with the function granted stands in for the old second super admin)
    keeper = create_user(
        session,
        SYS,
        email="keeper@example.org",
        password=PW,
        full_name="Keeper",
        role=Role.DIRECTORATE_USER,
        office=dse,
    )
    access.set_override(session, actor, sup, keeper, Permission.OFFICES_MANAGE, PermissionEffect.GRANT)
    with pytest.raises(Forbidden, match="own office"):
        offices.deactivate_office(session, access.actor_for(keeper), keeper, dse)


# ------------------------------------------------------------------------------------------------ delegation


def test_department_admin_delegation(session, world):
    edu, health, admin, actor = world["edu"], world["health"], world["admin"], world["admin_actor"]
    sup, sup_actor = world["super"], world["sup_actor"]
    with pytest.raises(Forbidden, match="offices.manage"):
        offices.create_office(
            session, actor, admin, code="EDU-DSE", name="DSE", kind="directorate", parent=edu
        )
    access.set_override(session, sup_actor, sup, admin, Permission.OFFICES_MANAGE, PermissionEffect.GRANT)
    dse = offices.create_office(
        session, actor, admin, code="EDU-DSE", name="DSE", kind="directorate", parent=edu
    )
    unit = offices.create_office(
        session, actor, admin, code="EDU-LEGAL", name="Legal", kind="unit", parent=edu
    )
    assert dse.created_by == admin.id and unit.path == "GOA/EDU/EDU-LEGAL"
    assert audits(session, "office.create", dse.id)[0].actor_office_code == "EDU"
    with pytest.raises(Forbidden, match="super admin"):
        offices.create_office(
            session, actor, admin, code="NEW", name="New", kind="department", parent=world["goa"]
        )
    with pytest.raises(Forbidden, match="outside"):
        offices.create_office(session, actor, admin, code="H-X", name="x", kind="directorate", parent=health)
    with pytest.raises(Forbidden):
        offices.update_office(session, actor, admin, edu, name="Mine")
    with pytest.raises(Forbidden):
        offices.deactivate_office(session, actor, admin, edu)
    with pytest.raises(Forbidden):  # another department: refused by kind and by scope
        offices.update_office(session, actor, admin, health, name="Theirs")
    # inside the subtree the admin edits and deactivates
    offices.update_office(session, actor, admin, dse, name="Directorate of Secondary Education")
    offices.deactivate_office(session, actor, admin, unit)
    assert not unit.is_active
    assert edu.name == "Education"


# ------------------------------------------------------------------------------------------------ admins


def test_add_department_admin(session, world):
    edu, sup, actor, admin = world["edu"], world["super"], world["sup_actor"], world["admin"]
    health = world["health"]
    # EDU has its admin: a second one is refused before anything is written (decision 14)
    with pytest.raises(AdminExists):
        offices.add_department_admin(
            session, actor, sup, edu, email="admin.edu@example.org", password=PW, full_name="Again"
        )
    assert offices.department_admins(session, edu) == [admin]
    user = offices.add_department_admin(
        session,
        actor,
        sup,
        health,
        email="Nodal.HEALTH@example.org",
        password=PW,
        full_name="Nodal Officer",
        designation="Joint Secretary",
    )
    assert user.role == Role.DEPT_ADMIN and user.office_id == health.id and user.must_confirm_profile
    assert user.email == "nodal.health@example.org"
    assert len(audits(session, "office.admin_added", health.id)) == 1
    assert audits(session, "office.admin_added", health.id)[0].after == {
        "user_id": str(user.id),
        "email": user.email,
    }
    assert len(audits(session, "user.create", user.id)) == 1
    assert offices.department_admins(session, health) == [user]
    assert Permission.USERS_CREATE in access.effective_permissions(session, user)
    # the directorate tier and an inactive office are refused
    dse = offices.create_office(
        session, actor, sup, code="EDU-DSE", name="DSE", kind="directorate", parent=edu
    )
    with pytest.raises(OfficeError, match="Department-tier"):
        offices.add_department_admin(
            session, actor, sup, dse, email="d@example.org", password=PW, full_name="D"
        )
    agri = offices.create_office(
        session,
        actor,
        sup,
        code="AGRI",
        name="Agriculture",
        kind="department",
        parent=world["goa"],
        head=head("AGRI"),
    )
    end_head(session, sup, agri)
    offices.deactivate_office(session, actor, sup, agri)
    with pytest.raises(OfficeError, match="inactive"):
        offices.add_department_admin(
            session, actor, sup, agri, email="h@example.org", password=PW, full_name="H"
        )
    # the dept admin cannot: dept_admin is not a delegable type
    with pytest.raises(Forbidden, match="super admin"):
        offices.add_department_admin(
            session, world["admin_actor"], admin, edu, email="a2@example.org", password=PW, full_name="A2"
        )


# ------------------------------------------------------------------------------------------------ designations


def test_designations(session, world):
    sup, actor, admin, admin_actor = world["super"], world["sup_actor"], world["admin"], world["admin_actor"]
    max_before = session.scalar(sa.select(sa.func.max(Designation.sort_order)))
    osd = offices.create_designation(session, actor, sup, code="osd", name="Officer on Special Duty")
    assert osd.code == "OSD" and osd.sort_order == max_before + 10 and osd.created_by == sup.id
    assert len(audits(session, "designation.create", osd.id)) == 1
    with pytest.raises(DuplicateCode):
        offices.create_designation(session, actor, sup, code="OSD", name="again")
    with pytest.raises(DuplicateCode):
        offices.create_designation(session, actor, sup, code="cs_sec", name="again")
    offices.update_designation(session, actor, sup, osd, name="OSD (Legal)", sort_order=5)
    assert osd.name == "OSD (Legal)" and osd.sort_order == 5
    row = audits(session, "designation.update", osd.id)[0]
    assert (
        row.after == {"name": "OSD (Legal)", "sort_order": 5} and row.before["sort_order"] == max_before + 10
    )
    offices.set_designation_active(session, actor, sup, osd, False)
    assert not osd.is_active and osd.deactivated_at is not None and osd.valid_to == date.today()
    assert len(audits(session, "designation.deactivate", osd.id)) == 1
    with pytest.raises(OfficeError, match="already inactive"):
        offices.set_designation_active(session, actor, sup, osd, False)
    # a user created with a deactivated designation still resolves (historic rows keep their link)
    user = create_user(
        session,
        actor,
        email="hist@example.org",
        password=PW,
        full_name="Historic",
        role=Role.DEPT_OFFICER,
        office=world["edu"],
        designation_id=osd.id,
    )
    assert user.designation_id == osd.id
    offices.set_designation_active(session, actor, sup, osd, True)
    assert osd.is_active and osd.valid_to is None
    assert len(audits(session, "designation.reactivate", osd.id)) == 1
    # a department admin lacks admin.designations
    with pytest.raises(Forbidden, match="admin.designations"):
        offices.create_designation(session, admin_actor, admin, code="X", name="x")
    with pytest.raises(Forbidden):
        offices.update_designation(session, admin_actor, admin, osd, name="x")
    with pytest.raises(Forbidden):
        offices.set_designation_active(session, admin_actor, admin, osd, False)
    assert len(audits(session, "designation.create")) == 1


# ------------------------------------------------------------------------------------------------ tree


def test_office_tree_and_dependents(session, world):
    edu, health, sup, actor = world["edu"], world["health"], world["super"], world["sup_actor"]
    dse = offices.create_office(
        session, actor, sup, code="EDU-DSE", name="DSE", kind="directorate", parent=edu
    )
    unit = offices.create_office(session, actor, sup, code="EDU-X", name="x", kind="unit", parent=edu)
    offices.deactivate_office(session, actor, sup, unit)
    tree = offices.office_tree(session, [world["goa"]])
    assert [n.office.code for n in tree] == ["GOA"] and tree[0].tier == "state" and tree[0].users_active == 1
    kids = {n.office.code: n for n in tree[0].children}
    assert (
        set(kids) == {"EDU", "HEALTH"} and kids["EDU"].users_active == 2 and kids["HEALTH"].users_active == 1
    )
    assert [n.office.code for n in kids["EDU"].children] == ["EDU-DSE"] and kids["EDU"].children[0].depth == 2
    full = offices.office_tree(session, [world["goa"]], include_inactive=True)
    assert {n.office.code for n in full[0].children[0].children} == {"EDU-DSE", "EDU-X"}
    scoped = offices.office_tree(session, [edu])
    assert [n.office.code for n in scoped] == ["EDU"] and "HEALTH" not in str(
        [c.office.code for c in scoped[0].children]
    )
    assert offices.dependents(session, edu) == {"children": 1, "users": 2, "ownership": 0, "custody": 0}
    assert offices.dependents(session, dse) == {"children": 0, "users": 0, "ownership": 0, "custody": 0}
    assert offices.dependents(session, health)["users"] == 1  # its head


# ------------------------------------------------------------------------------------------------ seed


def test_seed_is_idempotent_with_the_43rd_function(session):
    wipe(session)
    first = seed_all(session)
    assert first.inserted["ref_permission"] == 49 and first.inserted["role_permissions"] == 9 * 49
    second = seed_all(session)
    assert second.total == 0
    assert session.scalar(sa.select(sa.func.count()).select_from(RolePermission)) == len(DEFAULT_MATRIX) * 49
    assert (
        session.scalar(
            sa.select(RolePermission.is_enabled).where(
                RolePermission.role == Role.DEPT_ADMIN,
                RolePermission.permission == Permission.ADMIN_DESIGNATIONS,
            )
        )
        is False
    )
    assert session.scalar(sa.text("select module from ref_permission where code = 'admin.designations'")) == (
        "admin"
    )
