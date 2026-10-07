"""Alert recipients per membership (design `user-memberships`, decision 11): an office's users are the logins with
an active membership at that office whose membership holds the function — found through a non-primary
membership, never through another membership's functions — and a person reached twice is notified once."""

from __future__ import annotations

import sqlalchemy as sa

from aslms.domain.alerts import Notification
from aslms.domain.reference import Permission, Role
from aslms.services import ownership as own
from aslms.services.recipients import Resolver
from tests.db.world import add_membership, make_case


def test_office_users_through_a_non_primary_membership(world):
    with world.Session() as s:
        person = world.user(s, "edu_admin")
        add_membership(s, person, world.office(s, "HEALTH"), Role.DEPT_OFFICER)
        r = Resolver(s)
        health = world.office(s, "HEALTH")
        ack = {u.email for u in r.office_users(health, Permission.ALERTS_ACKNOWLEDGE)}
        assert "admin.edu@example.org" in ack and "off.health@example.org" in ack
        # cases.allot is held by the EDU membership, not the HEALTH one: not a HEALTH nodal officer
        allot = {u.email for u in r.office_users(health, Permission.CASES_ALLOT)}
        assert allot == {"admin.health@example.org"}
        assert {
            u.email for u in r.department_holders(world.office(s, "EDU-DSE"), Permission.CASES_ALLOT)
        } == {
            "admin.edu@example.org",
            "head.edu@example.org",
        }


def test_a_person_reached_twice_is_notified_once(world):
    from aslms.services import notifications

    with world.Session() as s:
        person = world.user(s, "edu_admin")
        add_membership(s, person, world.office(s, "HEALTH"), Role.DEPT_OFFICER)
        h_actor, h_admin = world.actor(s, "health_admin")
        case = make_case(s)
        own.claim(s, h_actor, h_admin, case, officer_user_id=person.id)
        r = Resolver(s)
        users = r.case_recipients(case)  # the custody holder and the allotted officer: the same person
        assert [u.id for u in users].count(person.id) == 2
        final = r.finalise(users, case)
        assert [u.id for u in final] == [person.id]
        from aslms.domain.alerts import Alert, AlertStatus, Severity

        alert = Alert(
            case_id=case.id,
            kind="ownership",
            office_id=world.office(s, "HEALTH").id,
            severity=Severity.NORMAL,
            status=AlertStatus.OPEN,
            title="t",
            data={},
            dedupe_key="test:twice",
            ref_no="ASLMS/GOA/ALR/2026/999999",
        )
        s.add(alert)
        s.flush()
        notifications.notify(s, alert, users, Severity.NORMAL)
        n = s.scalar(
            sa.select(sa.func.count()).where(
                Notification.alert_id == alert.id,
                Notification.user_id == person.id,
                Notification.channel == "in_app",
            )
        )
        assert n == 1
