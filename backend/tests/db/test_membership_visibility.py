"""Visibility is the union of the memberships' bases (design `user-memberships`, decision 7): the EDU admin who
is a HEALTH officer sees EDU-owned cases (whole department) and HEALTH cases only on personal bases, private
records of either office, and alerts addressed to either department; a one-membership user is unchanged."""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from aslms.domain.alerts import Alert
from aslms.domain.reference import Role
from aslms.services import ownership as own
from aslms.services import visibility as vis
from tests.db.world import add_membership, make_case


@pytest.fixture()
def dual(world):
    with world.Session() as s:
        add_membership(s, world.user(s, "edu_admin"), world.office(s, "HEALTH"), Role.DEPT_OFFICER)
        s.commit()
    return world


def test_cases_of_both_departments_on_their_own_bases(dual):
    w = dual
    with w.Session() as s:
        person = w.user(s, "edu_admin")
        e_actor, _ = w.actor(s, "edu_admin")
        h_actor, h_admin = w.actor(s, "health_admin")
        edu_case = make_case(s)
        own.claim(s, e_actor, person, edu_case)
        health_other = make_case(s)
        own.claim(s, h_actor, h_admin, health_other, officer_user_id=w.user(s, "health_off").id)
        health_mine = make_case(s)
        own.claim(s, h_actor, h_admin, health_mine, officer_user_id=person.id)
        assert "owner" in vis.access_basis(s, person, edu_case)
        assert not vis.can_view_case(s, person, health_other)  # HEALTH: personal bases only
        names = vis.access_basis(s, person, health_mine)
        assert {"allotted", "custody"} <= set(names)
        by_member = {m.department.code: names for m, names in vis.basis_by_member(s, person, health_mine)}
        assert {"allotted", "custody"} <= set(by_member["HEALTH"]) and "allotted" not in by_member["EDU"]
        # the membership that writes on the HEALTH case is the one holding the file
        writer = vis.acting_member_for_case(s, person, health_mine, vis.Permission.NOTES_ADD)
        assert writer.department.code == "HEALTH"
        writer = vis.acting_member_for_case(s, person, edu_case, vis.Permission.NOTES_ADD)
        assert writer.department.code == "EDU"


def _private(s, person, office_id, author=None) -> bool:
    cond = vis.record_visibility_condition(
        s,
        person,
        visibility=sa.literal("private_to_office"),
        office_id=sa.literal(office_id, PG_UUID(as_uuid=True)),
        author_user_id=sa.literal(author or uuid.uuid4(), PG_UUID(as_uuid=True)),
    )
    return bool(s.scalar(sa.select(cond)))


def test_private_records_of_either_office_and_alerts_of_either_department(dual):
    w = dual
    with w.Session() as s:
        person = w.user(s, "edu_admin")
        assert _private(s, person, w.office(s, "HEALTH").id)  # the HEALTH membership's office
        assert _private(s, person, w.office(s, "EDU-DSE").id)  # EDU, whole department
        assert not _private(s, person, w.office(s, "CENTRAL").id)
        assert not _private(s, w.user(s, "health_off"), w.office(s, "EDU").id)
        for code, seen in (("HEALTH", True), ("EDU-DHE", True), ("CENTRAL", False)):
            alert = Alert(office_id=w.office(s, code).id)
            assert vis.addressed_to_department(s, person, alert) is seen
        assert [d.code for d in vis.departments(s, person)] == ["EDU", "HEALTH"]


def test_a_one_membership_user_is_unchanged(world):
    with world.Session() as s:
        off1 = world.user(s, "edu_off1")
        names = [n for n, _ in vis.visibility_bases(s, off1)]
        assert names == ["allotted", "custody", "request"]
        counsel = world.user(s, "edu_counsel")
        assert [n for n, _ in vis.visibility_bases(s, counsel)] == [
            "allotted",
            "custody",
            "request",
            "counsel",
        ]
        assert [n for n, _ in vis.visibility_bases(s, world.user(s, "oversight"))] == ["state"]
        assert vis.visibility_bases(s, world.user(s, "edu_admin"))[0][0] == "owner"
