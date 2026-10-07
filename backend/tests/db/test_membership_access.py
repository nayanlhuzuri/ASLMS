"""Authority per membership (design `user-memberships`, decisions 5, 6, 8, 9): the EDU admin who is also a HEALTH
officer allots EDU cases but not HEALTH ones, grants EDU users only what the EDU membership holds, cannot manage
HEALTH users, and the HEALTH admin manages the HEALTH membership but not the login; overrides stay on their
membership."""

from __future__ import annotations

import pytest

from aslms.domain.org import PermissionEffect
from aslms.domain.reference import Permission, Role
from aslms.services import access, memberships
from aslms.services import ownership as own
from aslms.services.access import Forbidden
from tests.db.world import add_membership, make_case


@pytest.fixture()
def dual(world):
    """The EDU admin gains a HEALTH officer membership (the two-department person)."""
    with world.Session() as s:
        add_membership(
            s, world.user(s, "edu_admin"), world.office(s, "HEALTH"), Role.DEPT_OFFICER, "Under Secretary"
        )
        s.commit()
    return world


def test_allots_edu_cases_and_not_health_cases(dual):
    w = dual
    with w.Session() as s:
        actor, person = w.actor(s, "edu_admin")
        edu_case = make_case(s)
        own.claim(s, actor, person, edu_case)  # the EDU membership claims (the HEALTH one cannot)
        row = own.allot(s, actor, person, edu_case, officer_user_id=w.user(s, "edu_off1").id)
        assert row.office_id == w.office(s, "EDU").id and row.officer_user_id == w.user(s, "edu_off1").id
        # a HEALTH case claimed by HEALTH
        h_actor, h_admin = w.actor(s, "health_admin")
        health_case = make_case(s)
        own.claim(s, h_actor, h_admin, health_case, officer_user_id=w.user(s, "health_off").id)
        # the HEALTH membership relates to the case but lacks cases.allot
        with pytest.raises(Forbidden, match="cases.allot"):
            own.allot(s, actor, person, health_case, officer_user_id=person.id)
        # claiming for HEALTH is refused: the HEALTH membership lacks cases.claim
        pool_case = make_case(s)
        with pytest.raises(Forbidden, match="cases.claim"):
            own.claim(s, actor, person, pool_case, office_code="HEALTH")
        # take over in HEALTH works through the HEALTH officer membership unless that membership is denied it
        health_m = w.membership(s, "edu_admin", "HEALTH")
        access.set_override(s, h_actor, h_admin, health_m, Permission.CASES_TAKE_OVER, PermissionEffect.DENY)
        with pytest.raises(own.NotVisible):
            own.take_over(s, actor, person, health_case)
        access.set_override(s, h_actor, h_admin, health_m, Permission.CASES_TAKE_OVER, None)
        result = own.take_over(s, actor, person, health_case)
        assert (
            result.ownership.officer_user_id == person.id and result.previous.id == w.user(s, "health_off").id
        )
        assert result.ownership.office_id == w.office(s, "HEALTH").id


def test_grants_only_what_the_edu_membership_holds_and_cannot_manage_health(dual):
    w = dual
    with w.Session() as s:
        actor, person = w.actor(s, "edu_admin")
        off1 = w.membership(s, "edu_off1")
        row = access.set_override(s, actor, person, off1, Permission.CASES_CLAIM, PermissionEffect.GRANT)
        assert row.membership_id == off1.id and row.actor_office_code == "EDU"
        with pytest.raises(Forbidden, match="do not hold"):
            access.set_override(s, actor, person, off1, Permission.AUDIT_VIEW, PermissionEffect.GRANT)
        with pytest.raises(Forbidden, match="outside"):
            access.set_override(
                s,
                actor,
                person,
                w.membership(s, "health_off"),
                Permission.CASES_CLAIM,
                PermissionEffect.GRANT,
            )
        with pytest.raises(Forbidden, match="outside"):
            memberships.update(s, actor, person, w.membership(s, "health_off"), designation="X")
        with pytest.raises(access.ReservedFunction):
            access.set_override(s, actor, person, off1, Permission.ADMIN_TICKETS, PermissionEffect.GRANT)


def test_health_admin_ends_the_health_membership_but_not_the_login(dual):
    w = dual
    with w.Session() as s:
        h_actor, h_admin = w.actor(s, "health_admin")
        person = w.user(s, "edu_admin")
        # login-level actions follow the primary membership (EDU): the HEALTH admin is refused
        with pytest.raises(Forbidden):
            access.login_scope_member(s, h_admin, person, "reset_password")
        with pytest.raises(Forbidden):
            access.set_enabled(s, h_actor, h_admin, person, False)
        health_m = w.membership(s, "edu_admin", "HEALTH")
        fp = memberships.fingerprint(memberships.exit_items(s, health_m))
        memberships.end(
            s, h_actor, h_admin, health_m, reason="posting ended", assignments=[], items_fingerprint=fp
        )
        assert [m.department_id for m in access.active_memberships(s, person)] == [w.office(s, "EDU").id]
        assert person.is_active


def test_overrides_stay_on_their_membership(dual):
    w = dual
    with w.Session() as s:
        h_actor, h_admin = w.actor(s, "health_admin")
        person = w.user(s, "edu_admin")
        health_m = w.membership(s, "edu_admin", "HEALTH")
        access.set_override(s, h_actor, h_admin, health_m, Permission.NOTES_ADD, PermissionEffect.DENY)
        by_dept = {m.department.code: m for m in access.members(s, person)}
        assert not by_dept["HEALTH"].holds(Permission.NOTES_ADD)
        assert by_dept["EDU"].holds(Permission.NOTES_ADD)
        assert Permission.NOTES_ADD in access.effective_permissions(s, person)  # the union still has it
        assert Permission.CASES_ALLOT not in by_dept["HEALTH"].functions
