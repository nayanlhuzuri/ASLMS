"""The Department tab's order on `GET /inbox/claimed` (design case-inbox-simplify, decisions 9, 10 and 13): with
`case_state=all` active cases first; with `action` the file's due date next; `active` and `disposed` without
`action` keep the earlier order; the total equals `claimed_active + claimed_disposed`; `holder=elsewhere` is
outside the department and its units."""

from __future__ import annotations

from datetime import timedelta

import pytest

from aslms.domain.cases import Case, CaseStatus, NextHearingBasis
from aslms.domain.workflow import Custody, PendingAction
from aslms.services.workflow_common import today_ist
from tests.db import docs_support as ds
from tests.db import workflow_support as w


@pytest.fixture()
def api(world, tmp_path):
    w.widen(world)
    client = ds.make_api(world, tmp_path)
    yield client
    client.__exit__(None, None, None)


def ids(body) -> list[str]:
    return [str(i["case"]["id"]) for i in body["items"]]


def got(api, headers, query) -> dict:
    r = api.get(f"/inbox/claimed?{query}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture()
def dept(world):
    """EDU cases claimed by the admin. Active: `a1` (hearing in 9 days), `a2` (hearing in 2 days), `a3` (no hearing).
    Disposed: `d1` (a stale past hearing date, so it would lead a next-hearing order), `d2` (no hearing)."""
    today = today_ist()
    with world.Session() as s:
        out = {}
        for key, days, disposed in (
            ("a1", 9, False),
            ("a2", 2, False),
            ("a3", None, False),
            ("d1", -40, True),
            ("d2", None, True),
        ):
            case = w.claimed_case(s, world, officer="edu_off1")
            if days is not None:
                case.next_hearing_on = today + timedelta(days=days)
                case.next_hearing_basis = NextHearingBasis.COURT
            if disposed:
                case.status = CaseStatus.DISPOSED
            out[key] = case
            s.commit()  # one claim per transaction: claimed_at orders the ties
        return {k: str(v.id) for k, v in out.items()}


def test_claimed_all_active_first(api, world, dept):
    body = got(api, w.login(api, "edu_admin"), "case_state=all")
    assert ids(body) == [dept["a2"], dept["a1"], dept["a3"], dept["d1"], dept["d2"]]
    statuses = [i["case"]["status"] for i in body["items"]]
    assert statuses[-2:] == ["disposed", "disposed"] and "disposed" not in statuses[:3]


def test_claimed_all_total_equals_counts(api, world, dept):
    for key, query in (("edu_admin", ""), ("edu_head", ""), ("oversight", "office=EDU")):
        headers = w.login(api, key)
        r = api.get(f"/inbox/counts?{query}", headers=headers)
        assert r.status_code == 200, r.text
        block = next(d for d in r.json()["departments"] if d["office_code"] == "EDU")
        total = got(api, headers, f"case_state=all&{query}")["total"]
        assert total == block["claimed_active"] + block["claimed_disposed"] == 5, key


def test_claimed_action_orders_by_due(api, world, dept):
    today = today_ist()
    with world.Session() as s:
        for key, days in (("a1", -9), ("a2", -1), ("a3", -4), ("d1", -20)):
            held = s.get(Custody, dept[key])
            held.pending_action, held.due_date = PendingAction.EXAMINE, today + timedelta(days=days)
        s.commit()
    body = got(api, w.login(api, "edu_admin"), "case_state=all&action=overdue")
    # active first, the most overdue first; then the disposed overdue case
    assert ids(body) == [dept["a1"], dept["a3"], dept["a2"], dept["d1"]]


def test_claimed_active_and_disposed_order_unchanged(api, world, dept):
    admin = w.login(api, "edu_admin")
    assert ids(got(api, admin, "case_state=active")) == [dept["a2"], dept["a1"], dept["a3"]]
    assert ids(got(api, admin, "")) == [dept["a2"], dept["a1"], dept["a3"]]
    assert ids(got(api, admin, "case_state=disposed")) == [dept["d1"], dept["d2"]]


def test_holder_elsewhere_is_outside_subtree(api, world, dept):
    with world.Session() as s:
        w.send(s, world, "edu_off1", s.get(Case, dept["a1"]), "dse_user")  # the department's own unit
        w.send(s, world, "edu_off1", s.get(Case, dept["a2"]), "health_off")  # another department
        s.commit()
    admin = w.login(api, "edu_admin")
    assert ids(got(api, admin, "case_state=all&holder=elsewhere")) == [dept["a2"]]
    inside = ids(got(api, admin, "case_state=all&holder=department"))
    assert dept["a1"] in inside and dept["a2"] not in inside
