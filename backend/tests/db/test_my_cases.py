"""The caller's own cases (design portal-ui-redesign, A1 and A2): `GET /inbox/mine` in its four views and
`GET /inbox/mine/counts` — allotted, file and claimed sets, the directorate user's unit allotment, `files` equal
to `/custody/held?scope=me`, visibility (a lost membership and another department), merged cases, the filters,
the 400s and the 403, and that reading writes no audit row."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from aslms.domain.cases import Case, CaseStatus
from aslms.domain.events import AuditLog
from aslms.domain.org import UserMembership
from aslms.domain.ownership import Recommendation, RecommendationOrigin, ScoreBand
from aslms.domain.reference import Role
from aslms.domain.workflow import Custody, PendingAction
from aslms.services import my_cases, stages
from aslms.services import ownership as own
from aslms.services.workflow_common import today_ist
from tests.db import docs_support as ds
from tests.db import workflow_support as w
from tests.db.world import add_membership, make_case


@pytest.fixture()
def api(world, tmp_path):
    w.widen(world)
    client = ds.make_api(world, tmp_path)
    yield client
    client.__exit__(None, None, None)


def ids(body) -> list[str]:
    return [str(i["case"]["id"]) for i in body["items"]]


@pytest.fixture()
def cases(world, api):
    """EDU cases claimed by the EDU admin:
    - `a`: allotted to off1, who holds its file;
    - `b`: allotted to off2, file sent by off2 to off1 (off1 holds it, not allotted);
    - `c`: allotted to off2 (a colleague's), file with off2;
    - `d`: allotted to the unit EDU-DSE, no officer (the directorate user's);
    - `x`: disposed, allotted to off1;
    - `h`: claimed by the EDU head (a colleague of the admin);
    - `t`: claimed by HEALTH, transferred to EDU and accepted by the EDU admin."""
    with world.Session() as s:
        a = w.claimed_case(s, world, officer="edu_off1")
        b = w.claimed_case(s, world, officer="edu_off2")
        w.send(s, world, "edu_off2", b, "edu_off1")
        c = w.claimed_case(s, world, officer="edu_off2")
        d = make_case(s)
        actor, admin = world.actor(s, "edu_admin")
        own.claim(s, actor, admin, d, unit_code="EDU-DSE")
        x = w.claimed_case(s, world, officer="edu_off1")
        x.status = CaseStatus.DISPOSED
        h = make_case(s)
        h_actor, head = world.actor(s, "edu_head")
        own.claim(s, h_actor, head, h)
        t = make_case(s)
        ha, health = world.actor(s, "health_admin")
        own.claim(s, ha, health, t)
        tr = own.request_transfer(s, ha, health, t, to_office_code="EDU", reason="belongs to education")
        own.decide_transfer(s, actor, admin, tr, accept=True)
        s.commit()
        return {k: str(v.id) for k, v in dict(a=a, b=b, c=c, d=d, x=x, h=h, t=t).items()}


def mine(api, headers, view, query=""):
    r = api.get(f"/inbox/mine?view={view}&{query}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_working_files_claimed_disposed_for_an_officer(api, world, cases):
    off1 = w.login(api, "edu_off1")
    working = mine(api, off1, "working")
    assert sorted(ids(working)) == sorted([cases["a"], cases["b"]])
    assert cases["c"] not in ids(working)
    by_id = {str(i["case"]["id"]): i for i in working["items"]}
    assert sorted(by_id[cases["a"]]["reasons"]) == ["allotted", "file"]
    assert by_id[cases["b"]]["reasons"] == ["file"]
    item = by_id[cases["b"]]
    assert item["owner_code"] == "EDU"
    assert item["allotment"]["officer"]["full_name"] == "Edu Off2"
    assert item["custody"]["with_me"] is True and item["custody"]["pending_action"] == "parawise_comments"
    assert item["custody"]["holder_user"]["full_name"] == "Edu Off1"
    assert "remark" not in item["custody"]
    # every file I hold, whatever the case's status (the disposed `x` too)
    assert sorted(ids(mine(api, off1, "files"))) == sorted([cases["a"], cases["b"], cases["x"]])
    assert ids(mine(api, off1, "claimed")) == []
    assert ids(mine(api, off1, "disposed")) == [cases["x"]]


def test_a_directorate_user_sees_their_units_allotted_case(api, world, cases):
    dse = w.login(api, "dse_user")
    assert ids(mine(api, dse, "working")) == [cases["d"]]
    assert mine(api, dse, "working")["items"][0]["reasons"] == ["allotted"]
    # the other directorate's user does not
    assert ids(mine(api, w.login(api, "dhe_user"), "working")) == []


def test_files_equals_custody_held_scope_me(api, world, cases):
    off1 = w.login(api, "edu_off1")
    with world.Session() as s:
        # different due dates so the order is meaningful
        for key, days in (("a", 9), ("b", 3), ("x", 20)):
            s.get(Custody, cases[key]).due_date = today_ist() + timedelta(days=days)
        s.commit()
    files = mine(api, off1, "files")
    held = api.get("/custody/held?scope=me", headers=off1).json()
    assert ids(files) == ids(held) == [cases["b"], cases["a"], cases["x"]]
    assert files["total"] == held["total"]


def test_claimed_lists_my_claims_and_accepted_transfers(api, world, cases):
    admin = w.login(api, "edu_admin")
    claimed = ids(mine(api, admin, "claimed"))
    assert cases["t"] in claimed
    assert {cases["a"], cases["b"], cases["c"], cases["d"]} <= set(claimed)
    assert cases["h"] not in claimed  # the head claimed it
    assert cases["x"] not in claimed  # disposed
    assert ids(mine(api, w.login(api, "edu_head"), "claimed")) == [cases["h"]]
    disposed = ids(mine(api, admin, "disposed"))
    assert disposed == [cases["x"]]


def test_the_accepted_transfer_counts_when_a_watcher_row_was_promoted(world, api):
    """The receiving department already watched the case: its watcher row (written by someone else) becomes the
    primary on accept, and the person who accepted still finds it under Claimed by me."""
    with world.Session() as s:
        t = make_case(s)
        ha, health = world.actor(s, "health_admin")
        own.claim(s, ha, health, t)
        s.add(
            Recommendation(
                case_id=t.id,
                office_id=world.offices["EDU"].id,
                score=0.9,
                band=ScoreBand.HIGH,
                origin=RecommendationOrigin.CAUSE_LIST,
                actor_name="matching",
            )
        )
        s.flush()
        h_actor, head = world.actor(s, "edu_head")
        own.claim(s, h_actor, head, t)  # EDU watches (the case is owned by HEALTH)
        tr = own.request_transfer(s, ha, health, t, to_office_code="EDU", reason="belongs to education")
        actor, admin = world.actor(s, "edu_admin")
        own.decide_transfer(s, actor, admin, tr, accept=True)
        s.commit()
        t_id = str(t.id)
    assert t_id in ids(mine(api, w.login(api, "edu_admin"), "claimed"))


def test_visibility_lost_membership_and_another_department(api, world, cases):
    with world.Session() as s:
        off1 = world.user(s, "edu_off1")
        add_membership(s, off1, world.office(s, "HEALTH"), Role.DEPT_OFFICER, "Section Officer")
        hc = make_case(s)
        ha, health = world.actor(s, "health_admin")
        own.claim(s, ha, health, hc, officer_user_id=off1.id)
        s.commit()
        hc_id = str(hc.id)
    headers = w.login(api, "edu_off1")
    assert hc_id in ids(mine(api, headers, "working"))
    assert hc_id in ids(mine(api, headers, "files"))
    with world.Session() as s:
        m = world.membership(s, "edu_off1", "HEALTH")
        m.is_active, m.deactivated_at = False, datetime.now(UTC)
        s.commit()
    for view in my_cases.VIEWS:
        assert hc_id not in ids(mine(api, headers, view)), view
    # the custody row still names the person: only the visibility rule keeps the case out
    with world.Session() as s:
        assert str(s.get(Custody, hc_id).holder_user_id) == str(world.users["edu_off1"].id)
    # another department's officer sees nothing of EDU's
    health_off = w.login(api, "health_off")
    for view in my_cases.VIEWS:
        assert mine(api, health_off, view)["total"] == 0, view
    assert api.get("/inbox/mine/counts", headers=health_off).json() == {
        "working": 0,
        "files": 0,
        "claimed": 0,
        "disposed": 0,
    }


def test_merged_cases_are_excluded(api, world, cases):
    with world.Session() as s:
        s.get(Case, cases["a"]).merged_into_case_id = s.get(Case, cases["c"]).id
        s.commit()
    off1 = w.login(api, "edu_off1")
    for view in my_cases.VIEWS:
        assert cases["a"] not in ids(mine(api, off1, view)), view


def test_filters_stage_and_action_narrow(api, world, cases):
    with world.Session() as s:
        actor, admin = world.actor(s, "edu_admin")
        stages.set_stage(s, actor, admin, s.get(Case, cases["a"]), stage="counsel_briefed")
        s.get(Case, cases["b"]).reg_year = 2024
        s.get(Custody, cases["b"]).due_date = today_ist() - timedelta(days=4)
        held_a = s.get(Custody, cases["a"])
        # `a` came to off1 on the claim's ownership leg (no action pending): an action is set directly
        held_a.due_date, held_a.pending_action = today_ist() + timedelta(days=3), PendingAction.EXAMINE
        s.get(Custody, cases["c"]).due_date = today_ist() - timedelta(days=9)  # a colleague's file
        s.commit()
    off1 = w.login(api, "edu_off1")
    assert ids(mine(api, off1, "working", "stage=counsel_briefed")) == [cases["a"]]
    assert ids(mine(api, off1, "working", "stage=none")) == [cases["b"]]
    assert ids(mine(api, off1, "working", "year=2024")) == [cases["b"]]
    overdue = mine(api, off1, "working", "action=overdue")
    assert ids(overdue) == [cases["b"]]
    assert overdue["items"][0]["custody"]["overdue"] is True
    assert overdue["items"][0]["custody"]["overdue_days"] == 4
    assert ids(mine(api, off1, "working", "action=due_week")) == [cases["a"]]
    item = mine(api, off1, "working", "stage=counsel_briefed")["items"][0]
    assert item["stage"]["stage"] == "counsel_briefed" and item["stage"]["label"]


def test_bad_values_and_the_function(api, world, cases):
    off1 = w.login(api, "edu_off1")
    for query in (
        "view=everything",
        "view=working&stage=nonsense",
        "view=working&action=soon",
        "view=working&year=1",
    ):
        r = api.get(f"/inbox/mine?{query}", headers=off1)
        assert r.status_code == 400, (query, r.text)
    assert api.get("/inbox/mine", headers=off1).status_code == 422  # view is required
    assert api.get("/inbox/mine?view=working").status_code == 401
    assert api.get("/inbox/mine/counts").status_code == 401


def test_reading_writes_no_audit_row_and_counts_equal_totals(api, world, cases):
    logins = {key: w.login(api, key) for key in ("edu_off1", "edu_admin", "dse_user")}
    with world.Session() as s:
        before = s.scalar(sa.select(sa.func.count()).select_from(AuditLog))
    for key, headers in logins.items():
        counts = api.get("/inbox/mine/counts", headers=headers).json()
        for view in my_cases.VIEWS:
            assert counts[view] == mine(api, headers, view)["total"], (key, view)
    with world.Session() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(AuditLog)) == before


def test_a_login_without_view_scope_is_refused(world):
    from aslms.services.access import Forbidden

    with world.Session() as s:
        user = world.user(s, "edu_off1")
        for m in s.scalars(sa.select(UserMembership).where(UserMembership.user_id == user.id)).all():
            m.is_active, m.is_primary, m.deactivated_at = False, False, datetime.now(UTC)
        s.flush()
        with pytest.raises(Forbidden):
            my_cases.mine(s, user, view="working")
        with pytest.raises(Forbidden):
            my_cases.mine_counts(s, user)
        s.rollback()
