"""Who receives a case alert (design alerts-notifications, decision 14): the allotted officer and the custody
holder; no officer → the unit's users; neither → the department's nodal users; a watcher department's nodal
users; an inactive user and a user who cannot see the case are excluded; standing counsel never; the actor
is removed; the office an alert is addressed to."""

from __future__ import annotations

from datetime import UTC, datetime

from aslms.domain.org import PermissionEffect
from aslms.domain.reference import Permission
from aslms.services import access
from aslms.services.recipients import Resolver, owning_office
from tests.db import alerts_support as h
from tests.db.world import make_case


def emails(users) -> set[str]:
    return {u.email for u in users}


def recipients(s, case, **kw) -> set[str]:
    r = Resolver(s)
    return emails(r.finalise(r.case_recipients(case), case, **kw))


def test_officer_and_custody_holder(world):
    with world.Session() as s:
        case = make_case(s)
        h.claim(s, world, "edu_admin", case, officer_user_id=world.users["edu_off1"].id)
        # allotment put custody with the officer; a hand-over to a colleague adds them
        assert recipients(s, case) == {"off1.edu@example.org"}
        h.custody_at(s, case, world.office(s, "EDU"), world.user(s, "edu_off2"))
        assert recipients(s, case) == {"off1.edu@example.org", "off2.edu@example.org"}
        # the user whose action caused the event is removed
        assert recipients(s, case, exclude_user_id=world.users["edu_off1"].id) == {"off2.edu@example.org"}
        assert owning_office(s, case).code == "EDU"


def test_no_officer_unit_users_then_department_nodal_users(world):
    with world.Session() as s:
        unit_case = make_case(s)
        h.claim(s, world, "edu_admin", unit_case, unit_code="EDU-DSE")
        assert recipients(s, unit_case) == {"user.dse@example.org"}
        dept_case = make_case(s)
        h.claim(s, world, "edu_admin", dept_case)
        # the department holds the case and its custody: only the nodal officers (cases.allot), not every
        # officer, reviewer or counsel of the department
        assert recipients(s, dept_case) == {"admin.edu@example.org", "head.edu@example.org"}


def test_watcher_department_included(world):
    with world.Session() as s:
        case = make_case(s)
        h.claim(s, world, "edu_admin", case, officer_user_id=world.users["edu_off1"].id)
        h.recommend(s, world, case, "HEALTH")
        h.claim(s, world, "health_admin", case)  # HEALTH becomes a watcher
        assert recipients(s, case) == {"off1.edu@example.org", "admin.health@example.org"}


def test_inactive_and_non_visible_users_excluded(world):
    with world.Session() as s:
        case = make_case(s)
        h.claim(s, world, "edu_admin", case, officer_user_id=world.users["edu_off1"].id)
        h.custody_at(s, case, world.office(s, "EDU"), world.user(s, "edu_off2"))
        off2 = world.user(s, "edu_off2")
        off2.is_active, off2.deactivated_at = False, datetime.now(UTC)
        s.flush()
        assert recipients(s, case) == {"off1.edu@example.org"}
        actor, root = world.actor(s, "root")
        access.set_override(
            s, actor, root, world.user(s, "edu_off1"), Permission.CASES_VIEW_SCOPE, PermissionEffect.DENY
        )
        assert recipients(s, case) == set()
        s.rollback()


def test_standing_counsel_never_a_recipient(world):
    with world.Session() as s:
        case = make_case(s)
        h.claim(s, world, "edu_admin", case, unit_code="EDU-SC")
        h.custody_at(s, case, world.office(s, "EDU-SC"), world.user(s, "edu_counsel"))
        # the unit has only the counsel, who is never a recipient; the department's nodal users stand in
        assert recipients(s, case) == {"admin.edu@example.org", "head.edu@example.org"}
        s.rollback()
