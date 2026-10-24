"""A login with a State-wide membership and a working department membership (design `followups-oct`, decision 18):
working bases are read per membership, never from the State-merged list, so such a login sees custody remarks, its
own cases in My calendar and the working paths, as a department-only login does; sight is unchanged."""

from __future__ import annotations

from datetime import timedelta

import pytest

from aslms.core.clock import today_ist
from aslms.domain.cases import Case
from aslms.domain.reference import Permission, Role
from aslms.services import custody, workflow_common
from aslms.services import visibility as vis
from tests.db import docs_support as ds
from tests.db import workflow_support as w
from tests.db.world import add_membership, make_case

REMARK = "please act (oversight to edu_counsel)"


@pytest.fixture()
def dual(world):
    """State oversight is also an EDU officer; an EDU case is allotted to that login, which sends the file to the EDU
    standing counsel with a remark (so its working basis is `allotted`, not custody)."""
    with world.Session() as s:
        add_membership(s, world.user(s, "oversight"), world.office(s, "EDU"), Role.DEPT_OFFICER)
        s.commit()
    with world.Session() as s:
        case = w.claimed_case(s, world, officer="oversight")
        case.next_hearing_date = today_ist() + timedelta(days=3)
        w.send(s, world, "oversight", case, "edu_counsel")
        other = make_case(s)  # an unclaimed case: sight through `state` only
        s.commit()
        return {"case": case.id, "other": other.id}


def test_remark_shown_to_state_and_department_login(world, dual):
    with world.Session() as s:
        _, user = world.actor(s, "oversight")
        out = custody.history(s, user, s.get(Case, dual["case"]))
        assert out["card"]["remark"] == REMARK
        assert REMARK in {leg["remark"] for leg in out["legs"]}


def test_remark_hidden_from_state_only_login_without_view_private_all(world, dual):
    with world.Session() as s:
        _, user = world.actor(s, "central_op")
        out = custody.history(s, user, s.get(Case, dual["case"]))
        assert out["card"]["remark"] is None
        assert all(leg["remark"] is None for leg in out["legs"])


def test_my_calendar_lists_department_cases(world, dual, tmp_path):
    api = ds.make_api(world, tmp_path)
    try:
        r = api.get("/me/calendar", headers=w.login(api, "oversight"))
        assert r.status_code == 200, r.text
        hearings = {i["case"]["id"] for i in r.json()["items"] if i["kind"] == "hearing"}
        assert str(dual["case"]) in hearings
        assert str(dual["other"]) not in hearings
    finally:
        api.__exit__(None, None, None)
    with world.Session() as s:  # the hearing calendar's working condition reads every membership
        from aslms.services import calendar

        _, user = world.actor(s, "oversight")
        assert calendar.working_condition(s, user) is not None
        _, op = world.actor(s, "central_op")
        assert calendar.working_condition(s, op) is None


def test_works_on_case_true_through_department_membership(world, dual):
    with world.Session() as s:
        _, user = world.actor(s, "oversight")
        assert vis.access_basis(s, user, dual["case"]) == ["state"], "sight is unchanged: the merged list"
        assert vis.working_names(s, user, dual["case"]) == {"allotted"}
        assert vis.works_on_case(s, user, dual["case"]) is True
        assert vis.works_on_case(s, user, dual["other"]) is False
        _, op = world.actor(s, "central_op")
        assert vis.works_on_case(s, op, dual["case"]) is False


def test_missing_function_says_forbidden_not_not_working(world, dual):
    with world.Session() as s:
        _, user = world.actor(s, "oversight")
        case = s.get(Case, dual["case"])
        with pytest.raises(workflow_common.WorkflowError) as exc:
            workflow_common.acting_member(s, user, case, Permission.ADMIN_SCORING)
        assert exc.value.code == "forbidden"
        with pytest.raises(workflow_common.WorkflowError) as exc:
            workflow_common.acting_member(s, user, s.get(Case, dual["other"]), Permission.NOTES_ADD)
        assert exc.value.code == "not_working_on_case"
