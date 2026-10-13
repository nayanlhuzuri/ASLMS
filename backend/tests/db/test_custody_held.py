"""The shared case filters on the Files lists (design portal-filters, decisions 5 and 8): `GET /custody/held` in
each scope, the owner filter for a login tracking two departments, `GET /custody/sent` filtering rows whose case
the sender can no longer open, and a bad filter answering 400."""

from __future__ import annotations

from datetime import date

import pytest

from aslms.domain.cases import Case
from aslms.domain.ownership import CaseOwnership
from aslms.domain.reference import Role
from tests.db import docs_support as ds
from tests.db import workflow_support as w
from tests.db.world import SINGLE_BENCH, add_listing, add_membership

OCT1 = date(2026, 10, 1)


@pytest.fixture()
def api(world, tmp_path):
    w.widen(world)
    client = ds.make_api(world, tmp_path)
    yield client
    client.__exit__(None, None, None)


def case_ids(body) -> list[str]:
    return sorted(str(i["case"]["id"]) for i in body["items"])


@pytest.fixture()
def two_cases(world):
    """Two EDU cases allotted to (and held by) off1: `a` registered in 2025 and listed on 1 Oct in court 3 before
    a single bench, `b` registered in 2024 and never listed."""
    with world.Session() as s:
        a = w.claimed_case(s, world)
        a.case_type_text, a.reg_year = "WP(C)", 2025
        b = w.claimed_case(s, world)
        b.case_type_text, b.reg_year = "WA", 2024
        add_listing(s, a, OCT1, court_no="3", bench=SINGLE_BENCH)
        s.commit()
        return str(a.id), str(b.id)


def test_held_filters_each_scope(api, world, two_cases):
    a_id, b_id = two_cases
    off1 = w.login(api, "edu_off1")
    admin = w.login(api, "edu_admin")
    both = sorted([a_id, b_id])
    for headers, scope in ((off1, "me"), (admin, "office"), (admin, "owned")):

        def got(query, headers=headers, scope=scope):
            r = api.get(f"/custody/held?scope={scope}&{query}", headers=headers)
            assert r.status_code == 200, r.text
            return case_ids(r.json())

        assert got("") == both, scope
        assert got("year=2025") == [a_id], scope
        assert got("case_type=wa") == [b_id], scope
        assert got("listed_from=2026-10-01&listed_to=2026-10-01&court_no=3&bench=saikia") == [a_id], scope
        assert got("owner=EDU") == both, scope
        assert got("owner=FIN") == [], scope
        assert got("overdue=false&case_status=pending") == both, scope


def test_held_owner_filter_for_two_tracked_departments(api, world, two_cases):
    a_id, b_id = two_cases
    with world.Session() as s:
        add_membership(s, world.user(s, "edu_admin"), world.office(s, "HEALTH"), Role.DEPT_HEAD)
        hc = w.claimed_case(s, world, officer=None)
        # HEALTH owns `hc`: the ownership row is moved to HEALTH directly (tests only)
        row = s.query(CaseOwnership).filter_by(case_id=hc.id).one()
        row.office_id = world.offices["HEALTH"].id
        s.commit()
        hc_id = str(hc.id)
    admin = w.login(api, "edu_admin")
    r = api.get("/custody/held?scope=owned", headers=admin)
    assert r.status_code == 200, r.text
    assert case_ids(r.json()) == sorted([a_id, b_id, hc_id])
    assert case_ids(api.get("/custody/held?scope=owned&owner=EDU", headers=admin).json()) == sorted(
        [a_id, b_id]
    )
    assert case_ids(api.get("/custody/held?scope=owned&owner=health", headers=admin).json()) == [hc_id]


def test_sent_filters_invisible_case_rows(api, world, two_cases):
    """The HEALTH officer received both files and sent them on to FIN: their Sent rows name cases they can no
    longer open, and the filters match the facts those rows show."""
    a_id, b_id = two_cases
    with world.Session() as s:
        for cid in (a_id, b_id):
            w.send(s, world, "edu_off1", s.get(Case, cid), "health_off", due_date=w.in_days(5))
            w.send(s, world, "health_off", s.get(Case, cid), "fin_off", due_date=w.in_days(5))
        s.commit()
    hoff = w.login(api, "health_off")
    body = api.get("/custody/sent", headers=hoff).json()
    assert case_ids(body) == sorted([a_id, b_id])
    assert not any(i["visible"] for i in body["items"])  # no longer held: not visible
    r = api.get("/custody/sent?year=2025", headers=hoff)
    assert r.status_code == 200 and case_ids(r.json()) == [a_id] and r.json()["total"] == 1
    assert case_ids(api.get("/custody/sent?court_no=3", headers=hoff).json()) == [a_id]
    assert case_ids(api.get("/custody/sent?owner=EDU", headers=hoff).json()) == sorted([a_id, b_id])
    assert api.get("/custody/sent?owner=HEALTH", headers=hoff).json()["total"] == 0


def test_sent_bad_filter_400(api, world):
    off1 = w.login(api, "edu_off1")
    for query in ("year=1800", "owner=EDU-DSE", "next_from=2026-10-02&next_to=2026-10-01", "case_status=x"):
        r = api.get(f"/custody/sent?{query}", headers=off1)
        assert r.status_code == 400, query
    r = api.get("/custody/held?scope=me&owner=NOPE", headers=off1)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "bad_field"
