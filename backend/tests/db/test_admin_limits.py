"""Exactly one super admin and one department admin per department (design `user-memberships`, decisions 13-14):
the service and the partial unique indexes refuse a second one; the API paths never touch the super admin; the
CLI replacement ends the old one in the same transaction; the seed leaves an existing super admin alone; the
super admin's swap replaces a department admin, keeping or exiting the outgoing one. (The migration guard on
two super admins is in `test_memberships.py`.)"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from pydantic import SecretStr

from aslms.domain.events import AuditLog
from aslms.domain.org import RefreshToken, User, UserMembership
from aslms.domain.ownership import CaseOwnership, OwnershipStatus
from aslms.domain.reference import Role
from aslms.domain.workflow import Custody
from aslms.services import access, access_seed, memberships, offices
from aslms.services import ownership as own
from aslms.services.access import Conflict, Forbidden
from aslms.services.audit import Actor
from aslms.services.memberships import MembershipError
from aslms.services.seed import SeedReport
from tests.db.world import PW, make_case


def test_one_super_admin_service_index_and_api_paths(world):
    with world.Session() as s:
        root = world.user(s, "root")
        with pytest.raises(Conflict) as exc:
            memberships.insert_membership(
                s,
                Actor.system("t"),
                world.user(s, "health_off"),
                office=world.office(s, "GOA"),
                role=Role.SUPER_ADMIN,
            )
        assert exc.value.code == "super_admin_single"
        root_m = world.membership(s, "root")
        actor, _ = world.actor(s, "root")
        with pytest.raises(Forbidden) as e1:
            memberships.update(s, actor, root, root_m, role=Role.STATE_OVERSIGHT)
        with pytest.raises(Forbidden) as e2:
            memberships.end(s, actor, root, root_m, reason="no", assignments=[], items_fingerprint=None)
        with pytest.raises(Forbidden) as e3:
            access.set_enabled(s, actor, root, root, False)
        with pytest.raises(Forbidden) as e4:
            memberships.update(s, actor, root, world.membership(s, "edu_off1"), role=Role.SUPER_ADMIN)
        assert {e.value.code for e in (e1, e2, e3, e4)} == {"super_admin_cli_only"}
        s.rollback()
    with world.Session() as s:
        s.add(
            UserMembership(
                user_id=world.user(s, "edu_off1").id,
                office_id=world.office(s, "GOA").id,
                role=Role.SUPER_ADMIN,
            )
        )
        with pytest.raises(sa.exc.IntegrityError, match="ix_user_memberships_one_super_admin"):
            s.flush()


def test_replace_super_admin_from_the_cli(world):
    with world.Session() as s:
        root = world.user(s, "root")
        s.add(
            RefreshToken(
                user_id=root.id, token_hash="h-root-1", expires_at=sa.func.now() + sa.text("interval '1 day'")
            )
        )
        s.flush()
        # a login that already holds memberships cannot become the super admin
        with pytest.raises(Conflict) as exc:
            memberships.replace_super_admin(s, email="off1.edu@example.org")
        assert exc.value.code == "login_has_memberships"
        old, new = memberships.replace_super_admin(
            s, email="new.root@example.org", name="New Root", password=PW
        )
        assert old.id == root.id and not old.is_active
        assert (
            s.scalars(sa.select(RefreshToken.revoked_at).where(RefreshToken.user_id == root.id)).one()
            is not None
        )
        active = s.scalars(
            sa.select(UserMembership).where(UserMembership.role == Role.SUPER_ADMIN, UserMembership.is_active)
        ).all()
        assert [m.user_id for m in active] == [new.id] and active[0].is_primary
        ended = s.scalars(sa.select(UserMembership).where(UserMembership.user_id == root.id)).one()
        assert not ended.is_active and ended.end_reason == "replaced"
        row = s.scalars(sa.select(AuditLog).where(AuditLog.action == "membership.super_admin_replaced")).one()
        assert row.before["email"] == "root@example.org" and row.after["email"] == "new.root@example.org"
        assert access.is_super_admin(new) and not access.is_super_admin(old)


def test_seed_leaves_an_existing_super_admin_alone(world, monkeypatch):
    fake = SimpleNamespace(
        aslms_superadmin_email="someone.else@example.org", aslms_superadmin_password=SecretStr("x" * 12)
    )
    monkeypatch.setattr(access_seed, "get_settings", lambda: fake)
    with world.Session() as s:
        n = s.scalar(sa.select(sa.func.count()).select_from(User))
        report = SeedReport()
        holder = access_seed.seed_super_admin(s, report, world.office(s, "GOA"))
        assert holder.email == "root@example.org"
        assert report.notes == ["super admin exists (root@example.org); .env not used"]
        assert s.scalar(sa.select(sa.func.count()).select_from(User)) == n


def test_one_department_admin(world):
    with world.Session() as s:
        actor, root = world.actor(s, "root")
        with pytest.raises(Conflict) as exc:
            memberships.add(
                s,
                actor,
                root,
                world.user(s, "health_off"),
                office=world.office(s, "EDU"),
                role=Role.DEPT_ADMIN,
            )
        assert exc.value.code == "one_dept_admin"
        with pytest.raises(offices.AdminExists):
            offices.add_department_admin(
                s, actor, root, world.office(s, "EDU"), email="a2@example.org", password=PW, full_name="A2"
            )
        with pytest.raises(MembershipError) as exc2:
            memberships.add(
                s,
                actor,
                root,
                world.user(s, "health_off"),
                office=world.office(s, "EDU-DSE"),
                role=Role.DEPT_ADMIN,
            )
        assert exc2.value.code == "admin_at_department"
        s.rollback()
    with world.Session() as s:
        edu = world.office(s, "EDU")
        s.add(
            UserMembership(
                user_id=world.user(s, "health_off").id,
                office_id=edu.id,
                department_id=edu.id,
                role=Role.DEPT_ADMIN,
            )
        )
        with pytest.raises(sa.exc.IntegrityError, match="ix_user_memberships_one_dept_admin"):
            s.flush()


def test_swap_keeps_the_outgoing_admin_as_an_officer(world):
    with world.Session() as s:
        actor, root = world.actor(s, "root")
        a_actor, admin = world.actor(s, "edu_admin")
        case = make_case(s)
        own.claim(s, a_actor, admin, case, officer_user_id=admin.id)
        edu = world.office(s, "EDU")
        with pytest.raises(Forbidden):
            memberships.replace_department_admin(
                s, a_actor, admin, edu, incoming={"email": "x@example.org"}, reason="no"
            )
        new_admin, out = memberships.replace_department_admin(
            s,
            actor,
            root,
            edu,
            incoming={
                "email": "nodal.edu@example.org",
                "password": PW,
                "full_name": "Nodal EDU",
                "designation": "JS",
            },
            outgoing="dept_officer",
            reason="order of 1 Oct",
        )
        assert new_admin.role == Role.DEPT_ADMIN and new_admin.office_id == edu.id
        assert [u.email for u in offices.department_admins(s, edu)] == ["nodal.edu@example.org"]
        old = world.membership(s, "edu_admin")
        assert old.id == out["membership"] and old.role == Role.DEPT_OFFICER and old.is_active
        row = s.scalars(sa.select(CaseOwnership).where(CaseOwnership.case_id == case.id)).one()
        assert row.officer_user_id == admin.id and s.get(Custody, case.id).holder_user_id == admin.id
        audit = s.scalars(sa.select(AuditLog).where(AuditLog.action == "office.admin_replaced")).one()
        assert audit.after["outgoing"] == "dept_officer" and audit.before["role"] == "dept_admin"


def test_swap_with_end_needs_the_full_item_list(world):
    with world.Session() as s:
        actor, root = world.actor(s, "root")
        a_actor, admin = world.actor(s, "edu_admin")
        case = make_case(s)
        own.claim(s, a_actor, admin, case, officer_user_id=admin.id)
        s.commit()
        edu = world.office(s, "EDU")
        old_m = world.membership(s, "edu_admin")
        p = memberships.exit_preview(s, root, old_m)
        assert len(p["items"]) == 2
        with pytest.raises(Conflict) as exc:
            memberships.replace_department_admin(
                s,
                actor,
                root,
                edu,
                incoming={"membership": str(world.membership(s, "edu_off2").id)},
                outgoing="end",
                reason="transferred",
                assignments=[],
                items_fingerprint=p["items_fingerprint"],
            )
        assert exc.value.code == "unassigned_items"
        s.rollback()
    with world.Session() as s:
        actor, root = world.actor(s, "root")
        edu = world.office(s, "EDU")
        old_m = world.membership(s, "edu_admin")
        p = memberships.exit_preview(s, root, old_m)
        off1 = world.membership(s, "edu_off1")
        assignments = [{"key": i["key"], "to_membership": str(off1.id)} for i in p["items"]]
        new_admin, out = memberships.replace_department_admin(
            s,
            actor,
            root,
            edu,
            incoming={"membership": str(world.membership(s, "edu_off2").id)},
            outgoing="end",
            reason="transferred",
            assignments=assignments,
            items_fingerprint=p["items_fingerprint"],
        )
        assert new_admin.user_id == world.user(s, "edu_off2").id and new_admin.role == Role.DEPT_ADMIN
        assert access.active_memberships(s, world.user(s, "edu_admin")) == []
        assert len(out["reassigned"]) == 2
        assert s.scalars(
            sa.select(CaseOwnership.officer_user_id).where(CaseOwnership.status == OwnershipStatus.ACTIVE)
        ).all() == [off1.user_id]
        assert len(offices.department_admins(s, edu)) == 1
