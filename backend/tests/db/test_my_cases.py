"""The caller's own cases (design portal-ui-redesign, A1 and A2): `GET /inbox/mine` in its four views and
`GET /inbox/mine/counts` — allotted, file and claimed sets, the directorate user's unit allotment, `files` equal
to `/custody/held?scope=me`, visibility (a lost membership and another department), merged cases, the filters,
the 400s and the 403, and that reading writes no audit row."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from aslms.core.config import get_settings
from aslms.domain.cases import Case, CaseStatus
from aslms.domain.events import AuditLog
from aslms.domain.org import UserMembership
from aslms.domain.ownership import Recommendation, RecommendationOrigin, ScoreBand
from aslms.domain.reference import Role
from aslms.domain.workflow import Custody, CustodyHistory, PendingAction
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
    # the disposed `x` stays because off1 holds its file (design case-inbox-merge, decision 3)
    assert sorted(ids(working)) == sorted([cases["a"], cases["b"], cases["x"]])
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
    # the disposed `x` (file with off1) has no stage either
    assert sorted(ids(mine(api, off1, "working", "stage=none"))) == sorted([cases["b"], cases["x"]])
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


# ------------------------------------------------------------------- design case-inbox-merge, decisions 2 to 4


def test_working_includes_disposed_case_with_me(api, world, cases):
    """A disposed case whose file the caller holds is in Working on and in Disposed; a disposed case only
    allotted to the caller (the file is elsewhere) is in Disposed only."""
    with world.Session() as s:
        y = w.claimed_case(s, world, officer="edu_off1")
        w.send(s, world, "edu_off1", y, "edu_off2")  # allotted to off1, file with off2
        y.status = CaseStatus.DISPOSED
        s.commit()
        y_id = str(y.id)
    off1 = w.login(api, "edu_off1")
    working, disposed = ids(mine(api, off1, "working")), ids(mine(api, off1, "disposed"))
    assert cases["x"] in working and cases["x"] in disposed
    assert y_id not in working and y_id in disposed
    # the holder sees the disposed case it holds in Working on too
    assert y_id in ids(mine(api, w.login(api, "edu_off2"), "working"))


def test_working_order_my_due_first(api, world, cases):
    """My overdue file, my file due later, then an allotted case with a nearer hearing, then no dates. A case
    held by someone else with an earlier due date does not jump ahead."""
    today = today_ist()
    with world.Session() as s:
        # `a`: my file, due in 5 days; `b`: my file, overdue; `x` (disposed, mine) has no action
        held_a = s.get(Custody, cases["a"])
        held_a.pending_action, held_a.due_date = PendingAction.EXAMINE, today + timedelta(days=5)
        s.get(Custody, cases["b"]).due_date = today - timedelta(days=2)
        s.get(Case, cases["b"]).next_hearing_date = today + timedelta(days=40)
        # `e`: allotted to me, file with off2 due yesterday (not mine), hearing in 3 days
        e = w.claimed_case(s, world, officer="edu_off1")
        w.send(s, world, "edu_off1", e, "edu_off2")
        s.get(Custody, e.id).due_date = today - timedelta(days=9)
        e.next_hearing_date = today + timedelta(days=3)
        # `f`: allotted to me, file with off2, hearing in 10 days
        f = w.claimed_case(s, world, officer="edu_off1")
        w.send(s, world, "edu_off1", f, "edu_off2")
        f.next_hearing_date = today + timedelta(days=10)
        # `g`: allotted to me, file with off2, no dates
        g = w.claimed_case(s, world, officer="edu_off1")
        w.send(s, world, "edu_off1", g, "edu_off2")
        s.get(Custody, g.id).due_date = None
        s.commit()
        e_id, f_id, g_id = str(e.id), str(f.id), str(g.id)
    order = ids(mine(api, w.login(api, "edu_off1"), "working"))
    assert order[:4] == [cases["b"], cases["a"], e_id, f_id]
    assert order.index(g_id) > order.index(f_id)
    assert set(order[4:]) == {g_id, cases["x"]}


def test_brief_due_soon_window(api, world, cases):
    window = get_settings().request_due_soon_days
    today = today_ist()
    off1 = w.login(api, "edu_off1")

    def brief(days):
        with world.Session() as s:
            s.get(Custody, cases["b"]).due_date = None if days is None else today + timedelta(days=days)
            s.commit()
        items = {str(i["case"]["id"]): i for i in mine(api, off1, "working")["items"]}
        return items[cases["b"]]["custody"]

    assert brief(window)["due_soon"] is True
    assert brief(0)["due_soon"] is True
    assert brief(window + 1)["due_soon"] is False
    late = brief(-1)
    assert late["overdue"] is True and late["due_soon"] is False
    assert brief(None)["due_soon"] is False


def test_brief_sent_by_from_current_leg(api, world, cases):
    off1 = w.login(api, "edu_off1")
    items = {str(i["case"]["id"]): i for i in mine(api, off1, "working")["items"]}
    sent_by = items[cases["b"]]["custody"]["sent_by"]
    with world.Session() as s:
        leg = s.get(CustodyHistory, s.get(Custody, cases["b"]).current_leg_id)
        assert sent_by == {
            "name": leg.actor_name,
            "designation": leg.actor_designation,
            "office_code": leg.actor_office_code,
        }
        assert sent_by["name"] == "Edu Off2"
        # the chain is append-only: a new current leg written without an actor snapshot
        bare = CustodyHistory(
            case_id=leg.case_id,
            seq_no=leg.seq_no + 1,
            holder_office_id=leg.holder_office_id,
            holder_office_code=leg.holder_office_code,
            holder_user_id=leg.holder_user_id,
            holder_user_name=leg.holder_user_name,
            holder_membership_id=leg.holder_membership_id,
            holder_designation=leg.holder_designation,
            reason=leg.reason,
            pending_action=leg.pending_action,
            due_date=leg.due_date,
            remark=leg.remark,
        )
        s.add(bare)
        s.flush()
        s.get(Custody, cases["b"]).current_leg_id = bare.id
        s.commit()
    items = {str(i["case"]["id"]): i for i in mine(api, off1, "working")["items"]}
    assert items[cases["b"]]["custody"]["sent_by"] is None


def test_brief_has_no_remark(api, world, cases):
    off1 = w.login(api, "edu_off1")
    for view in ("working", "disposed"):
        for item in mine(api, off1, view)["items"]:
            assert item["custody"] is not None
            assert "remark" not in item["custody"], view
    # the remark is on the custody card only
    card = api.get(f"/cases/{cases['b']}/custody?order=desc&limit=1", headers=off1)
    assert card.status_code == 200, card.text
    assert card.json()["card"]["remark"] == "please act (edu_off2 to edu_off1)"


def test_working_count_matches_list(api, world, cases):
    for key in ("edu_off1", "edu_off2", "edu_admin", "dse_user"):
        headers = w.login(api, key)
        counts = api.get("/inbox/mine/counts", headers=headers).json()
        assert counts["working"] == mine(api, headers, "working")["total"], key


def test_claimed_items_carry_new_brief_fields(api, world, cases):
    admin = w.login(api, "edu_admin")
    body = api.get("/inbox/claimed", headers=admin).json()
    by_id = {str(i["case"]["id"]): i for i in body["items"]}
    custody = by_id[cases["b"]]["custody"]
    assert custody["due_soon"] in (True, False)
    assert custody["sent_by"]["name"] == "Edu Off2"
    assert "remark" not in custody


def test_openapi_brief_lists_the_new_fields(api):
    schema = api.get("/openapi.json").json()["components"]["schemas"]["CustodyBriefOut"]
    assert {"due_soon", "sent_by"} <= set(schema["properties"])
