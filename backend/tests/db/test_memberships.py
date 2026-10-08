"""Memberships (design `user-memberships`, decisions 1-3, 8, 9, 12, 22): migration 0008's back-fill, adding a
membership inside and outside the actor's scope, one active membership per department (service and index), the
super admin's single membership, the primary flag and the mirror, ended memberships, exact e-mail lookup, and
the audit rows."""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from alembic import command

from aslms.domain.events import AuditLog
from aslms.domain.org import UserMembership
from aslms.domain.reference import Permission, Role
from aslms.services import access, memberships
from aslms.services.access import Conflict, Forbidden
from tests.db.conftest import TEST_URL, alembic_config, head_revision, wipe


def audits(s, action: str, entity_id=None) -> list[AuditLog]:
    stmt = sa.select(AuditLog).where(AuditLog.action == action)
    if entity_id is not None:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    return list(s.scalars(stmt.order_by(AuditLog.created_at, AuditLog.id)))


# ------------------------------------------------------------------------------------------------ migration


REF_ROWS = """
INSERT INTO ref_office_kind (code, label) VALUES ('state', 'State'), ('department', 'Department'),
  ('directorate', 'Directorate');
INSERT INTO ref_role (code, label) VALUES ('super_admin', 'x'), ('dept_admin', 'x'), ('dept_officer', 'x'),
  ('directorate_user', 'x'), ('dept_head', 'x');
INSERT INTO ref_permission (code, label, module) VALUES ('cases.claim', 'Claim', 'cases');
INSERT INTO offices (id, code, name, kind, path) VALUES
  ('00000000-0000-7000-8000-000000000001', 'GOA', 'Assam', 'state', 'GOA');
INSERT INTO offices (id, code, name, kind, parent_id, path) VALUES
  ('00000000-0000-7000-8000-000000000002', 'EDU', 'Education', 'department',
   '00000000-0000-7000-8000-000000000001', 'GOA/EDU'),
  ('00000000-0000-7000-8000-000000000003', 'EDU-DSE', 'DSE', 'directorate',
   '00000000-0000-7000-8000-000000000002', 'GOA/EDU/EDU-DSE'),
  ('00000000-0000-7000-8000-000000000004', 'HEALTH', 'Health', 'department',
   '00000000-0000-7000-8000-000000000001', 'GOA/HEALTH');
"""


def _user_sql(uid: str, email: str, role: str, office: str, *, active: bool = True) -> str:
    deactivated = "NULL" if active else "now()"
    return (
        "INSERT INTO users (id, email, password_hash, full_name, designation, office_id, role, is_active, "
        f"deactivated_at) VALUES ('{uid}', '{email}', 'x', '{email}', 'Designation of {email}', "
        f"'00000000-0000-7000-8000-00000000000{office}', '{role}', {str(active).lower()}, {deactivated});"
    )


@pytest.fixture()
def at_0007(engine):
    """An empty database at revision 0007 with a few rows; back at head (wiped) afterwards."""
    cfg = alembic_config(TEST_URL)
    with engine.begin() as conn:
        wipe(conn)
    command.downgrade(cfg, "0007")
    with engine.begin() as conn:
        for stmt in REF_ROWS.strip().split(";\n"):
            if stmt.strip():
                conn.execute(sa.text(stmt))
    yield cfg
    command.upgrade(cfg, "head")
    with engine.begin() as conn:
        wipe(conn)


def test_backfill_gives_every_user_one_primary_membership_and_moves_overrides(engine, at_0007):
    u1, u2, u3 = (str(uuid.uuid4()) for _ in range(3))
    with engine.begin() as conn:
        conn.execute(sa.text(_user_sql(u1, "admin@example.org", "dept_admin", "2")))
        conn.execute(sa.text(_user_sql(u2, "dse@example.org", "directorate_user", "3")))
        conn.execute(sa.text(_user_sql(u3, "gone@example.org", "dept_officer", "4", active=False)))
        conn.execute(
            sa.text(
                "INSERT INTO user_permissions (user_id, permission, effect) VALUES (:u, 'cases.claim', 'grant')"
            ),
            {"u": u2},
        )
    command.upgrade(at_0007, "head")
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT u.email, m.office_id = u.office_id, m.role = u.role, m.designation = u.designation, "
                "m.is_primary, m.is_active, d.code FROM user_memberships m JOIN users u ON u.id = m.user_id "
                "LEFT JOIN offices d ON d.id = m.department_id ORDER BY u.email"
            )
        ).all()
        assert [tuple(r) for r in rows] == [
            ("admin@example.org", True, True, True, True, True, "EDU"),
            ("dse@example.org", True, True, True, True, True, "EDU"),
            ("gone@example.org", True, True, True, False, False, "HEALTH"),  # a disabled login: ended
        ]
        assert (
            conn.execute(sa.text("SELECT count(*) FROM users WHERE is_active")).scalar()
            == conn.execute(sa.text("SELECT count(*) FROM user_memberships WHERE is_primary")).scalar()
        )
        moved = conn.execute(
            sa.text(
                "SELECT m.user_id FROM user_permissions p JOIN user_memberships m ON m.id = p.membership_id"
            )
        ).scalar()
        assert str(moved) == u2
        assert (
            conn.execute(
                sa.text("SELECT count(*) FROM user_permissions WHERE membership_id IS NULL")
            ).scalar()
            == 0
        )


def test_migration_guard_stops_on_two_super_admins(engine, at_0007):
    with engine.begin() as conn:
        conn.execute(sa.text(_user_sql(str(uuid.uuid4()), "root1@example.org", "super_admin", "1")))
        conn.execute(sa.text(_user_sql(str(uuid.uuid4()), "root2@example.org", "super_admin", "1")))
    with pytest.raises(Exception, match="more than one active super admin"):
        command.upgrade(at_0007, "head")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE users SET is_active = false, deactivated_at = now() WHERE email = 'root2@example.org'"
            )
        )
        conn.execute(sa.text(_user_sql(str(uuid.uuid4()), "head1@example.org", "dept_head", "2")))
        conn.execute(sa.text(_user_sql(str(uuid.uuid4()), "head2@example.org", "dept_head", "3")))
    with pytest.raises(Exception, match="department admin or head"):
        command.upgrade(at_0007, "head")
    with engine.begin() as conn:
        conn.execute(sa.text("DELETE FROM users WHERE email = 'head2@example.org'"))


def test_downgrade_stops_on_a_second_membership(world):
    """The downgrade refuses while the old schema cannot hold the data."""
    from tests.db.world import add_membership

    with world.Session() as s:
        add_membership(s, world.user(s, "health_off"), world.office(s, "EDU-DSE"), Role.DIRECTORATE_USER)
        s.commit()
    with pytest.raises(Exception, match="several memberships"):
        command.downgrade(alembic_config(TEST_URL), "0007")
    with world.Session() as s:
        # the whole downgrade is one transaction: nothing was undone, the head stays
        assert s.execute(sa.text("select version_num from alembic_version")).scalar() == head_revision()


def test_downgrade_stops_on_a_ticket(world):
    """A ticket is a legal record: the downgrade refuses."""
    from aslms.services import tickets

    with world.Session() as s:
        r_actor, root = world.actor(s, "root")
        tickets.request_head_change(
            s, r_actor, root, {"operation": "end", "department_code": "EDU", "outgoing": {"mode": "retype"}}
        )
        s.commit()
    with pytest.raises(Exception, match="admin tickets exist"):
        command.downgrade(alembic_config(TEST_URL), "0007")
    with world.Session() as s:
        # the whole downgrade is one transaction: nothing was undone, the head stays
        assert s.execute(sa.text("select version_num from alembic_version")).scalar() == head_revision()


def test_migration_reports_headless_departments_and_creates_nothing(engine, at_0007):
    with engine.begin() as conn:
        conn.execute(sa.text(_user_sql(str(uuid.uuid4()), "admin@example.org", "dept_admin", "2")))
    command.upgrade(at_0007, "head")  # NOTICE: EDU and HEALTH have no head; the upgrade completes
    with engine.connect() as conn:
        assert conn.execute(sa.text("SELECT count(*) FROM user_memberships")).scalar() == 1
        assert (
            conn.execute(sa.text("SELECT count(*) FROM user_memberships WHERE role = 'dept_head'")).scalar()
            == 0
        )


# ------------------------------------------------------------------------------------------------ the service


def test_add_membership_inside_and_outside_scope(world):
    with world.Session() as s:
        actor, edu_admin = world.actor(s, "edu_admin")
        health_off = world.user(s, "health_off")
        dse = world.office(s, "EDU-DSE")
        m = memberships.add(
            s,
            actor,
            edu_admin,
            health_off,
            office=dse,
            role=Role.DIRECTORATE_USER,
            designation="Deputy Director",
        )
        assert m.is_active and not m.is_primary and m.department_id == world.office(s, "EDU").id
        assert health_off.office_id == world.office(s, "HEALTH").id  # the primary (mirror) is unchanged
        row = audits(s, "membership.added", m.id)[0]
        assert row.after["office_code"] == "EDU-DSE" and row.actor_office_code == "EDU"
        # another department is outside the EDU admin's scope
        with pytest.raises(Forbidden, match="outside"):
            memberships.add(
                s,
                actor,
                edu_admin,
                world.user(s, "edu_off1"),
                office=world.office(s, "HEALTH"),
                role=Role.DEPT_OFFICER,
            )
        # a type the department admin may not delegate
        with pytest.raises(Forbidden):
            memberships.add(
                s,
                actor,
                edu_admin,
                world.user(s, "health_admin"),
                office=world.office(s, "EDU-DHE"),
                role=Role.DEPT_ADMIN,
            )
        # a head only through the head-change request
        root_actor, root = world.actor(s, "root")
        with pytest.raises(Conflict) as exc:
            memberships.add(
                s,
                root_actor,
                root,
                world.user(s, "health_admin"),
                office=world.office(s, "EDU"),
                role=Role.DEPT_HEAD,
            )
        assert exc.value.code == "use_head_change"


def test_one_active_membership_per_department_service_and_index(world):
    with world.Session() as s:
        actor, edu_admin = world.actor(s, "edu_admin")
        health_off = world.user(s, "health_off")
        memberships.add(
            s, actor, edu_admin, health_off, office=world.office(s, "EDU-DSE"), role=Role.DIRECTORATE_USER
        )
        with pytest.raises(Conflict) as exc:
            memberships.add(
                s, actor, edu_admin, health_off, office=world.office(s, "EDU-DHE"), role=Role.DIRECTORATE_USER
            )
        assert exc.value.code == "one_per_department"
        s.rollback()
    with world.Session() as s:
        health_off = world.user(s, "health_off")
        edu = world.office(s, "EDU")
        s.add(
            UserMembership(
                user_id=health_off.id, office_id=edu.id, department_id=edu.id, role=Role.DEPT_OFFICER
            )
        )
        s.add(
            UserMembership(
                user_id=health_off.id,
                office_id=world.office(s, "EDU-DSE").id,
                department_id=edu.id,
                role=Role.DIRECTORATE_USER,
            )
        )
        with pytest.raises(sa.exc.IntegrityError, match="ix_user_memberships_one_per_department"):
            s.flush()


def test_super_admin_holds_no_second_membership(world):
    with world.Session() as s:
        actor, root = world.actor(s, "root")
        with pytest.raises(Conflict) as exc:
            memberships.add(s, actor, root, root, office=world.office(s, "HEALTH"), role=Role.DEPT_OFFICER)
        assert exc.value.code == "super_admin_single"
        with pytest.raises(Forbidden) as exc2:
            memberships.add(
                s,
                actor,
                root,
                world.user(s, "edu_off1"),
                office=world.office(s, "GOA"),
                role=Role.SUPER_ADMIN,
            )
        assert exc2.value.code == "super_admin_cli_only"


def test_make_primary_rewrites_the_mirror(world):
    with world.Session() as s:
        actor, edu_admin = world.actor(s, "edu_admin")
        root_actor, root = world.actor(s, "root")
        health_off = world.user(s, "health_off")
        m = memberships.add(
            s,
            actor,
            edu_admin,
            health_off,
            office=world.office(s, "EDU-DSE"),
            role=Role.DIRECTORATE_USER,
            designation="DD",
        )
        # the EDU admin's scope does not contain the current primary office (HEALTH)
        with pytest.raises(Forbidden):
            memberships.make_primary(s, actor, edu_admin, health_off, m)
        memberships.make_primary(s, root_actor, root, health_off, m)
        assert health_off.office_id == world.office(s, "EDU-DSE").id
        assert health_off.role == Role.DIRECTORATE_USER and health_off.designation == "DD"
        primaries = [x for x in access.active_memberships(s, health_off) if x.is_primary]
        assert primaries == [m]
        assert len(audits(s, "membership.primary_changed", m.id)) == 1


def test_ended_membership_has_no_functions_and_lookup_is_exact(world):
    with world.Session() as s:
        actor, edu_admin = world.actor(s, "edu_admin")
        health_off = world.user(s, "health_off")
        m = memberships.add(
            s, actor, edu_admin, health_off, office=world.office(s, "EDU-DSE"), role=Role.DIRECTORATE_USER
        )
        assert Permission.NOTES_ADD in access.membership_functions(s, m)
        fp = memberships.fingerprint(memberships.exit_items(s, m))
        result = memberships.end(
            s, actor, edu_admin, m, reason="back to Health", assignments=[], items_fingerprint=fp
        )
        assert (
            result.membership.is_active is False
            and m.valid_to is not None
            and m.end_reason == "back to Health"
        )
        assert access.membership_functions(s, m) == set()
        assert [x.department_id for x in access.active_memberships(s, health_off)] == [
            world.office(s, "HEALTH").id
        ]
        assert {a.action for a in s.scalars(sa.select(AuditLog).where(AuditLog.entity_id == m.id))} >= {
            "membership.added",
            "membership.exit",
            "membership.ended",
        }
        # reactivation brings it back (not primary: the login has one)
        memberships.reactivate(s, actor, edu_admin, m)
        assert m.is_active and not m.is_primary and len(audits(s, "membership.reactivated", m.id)) == 1
        assert memberships.lookup(s, "OFF.health@example.org").id == health_off.id
        assert memberships.lookup(s, "off.health") is None
        assert memberships.lookup(s, "health@example.org") is None
