"""Department discovery over the API (design `department-discovery`, "API"; owner's decisions of 14 Oct 2026): the
rule endpoints carry `discover`, `discoverable` and `discovery` and refuse `not_discoverable`; the Court search tab's
terms are scoped to the caller's subtree (another department's term is absent and its cases 404) and the super admin
sees all; a term's cases carry `claimable` and only the caller's departments' recommendation; a user's request for a
name and years queues searches and warns `searched_before` without writing; the Data collection block is for the data
readers only; the manual sweep needs `admin.data_load`; the pool's `found_for` keeps the department's never-owned
finds and refuses another department without `cases.view_all`; 401 without a session."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from aslms.api.main import create_app
from aslms.core.config import Settings
from aslms.domain.events import AuditLog
from aslms.domain.ops import FetchStatus
from aslms.domain.ownership import (
    CaseOwnership,
    DiscoveryHit,
    DiscoveryTerm,
    OwnershipRole,
    OwnershipStatus,
    Recommendation,
    RecommendationOrigin,
    ScoreBand,
)
from tests.db.auth_support import bearer
from tests.db.discovery_support import party_rows, years
from tests.db.world import PW, USERS, make_case


@pytest.fixture()
def api(world):
    settings = Settings(
        _env_file=None,
        aslms_jwt_secret="test-secret-of-at-least-thirty-two-characters",
        aslms_access_token_minutes=5,
    )
    app = create_app(settings, world.Session)
    with TestClient(app) as client:
        yield client


def login(api: TestClient, key: str) -> dict:
    return bearer(api, USERS[key][0], PW)


def _rec(s, world, case, code, score=0.8):
    s.add(
        Recommendation(
            case_id=case.id,
            office_id=world.offices[code].id,
            score=score,
            band=ScoreBand.MEDIUM,
            origin=RecommendationOrigin.DISCOVERY,
            actor_name="matching",
        )
    )


def _setup(api, world):
    """EDU's prefix pattern PRITAM SAIKIA and HEALTH's keyword ANIL BORA through the API; four cases, three found by
    EDU's term: A (pool, recommended to EDU), B (pool, recommended to HEALTH only), C (owned by HEALTH); D found by
    HEALTH's term only."""
    edu = login(api, "edu_admin")
    r = api.post(
        "/admin/name-patterns",
        json={"pattern": "Pritam Saikia", "kind": "prefix", "office_code": "EDU"},
        headers=edu,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["discover"] is True and body["discoverable"] is True and body["discovery"]["cases_found"] == 0
    health = login(api, "health_admin")
    r = api.post("/admin/keywords", json={"keyword": "anil bora", "office_code": "HEALTH"}, headers=health)
    assert r.status_code == 201 and r.json()["discover"] is True, r.text
    with world.Session() as s:
        terms = {t.term: t.id for t in s.scalars(sa.select(DiscoveryTerm))}
        a = make_case(s, pet="A")
        b = make_case(s, pet="B")
        c = make_case(s, pet="C")
        d = make_case(s, pet="D")
        make_case(s, pet="NOT FOUND")
        for case in (a, b, c):
            s.add(DiscoveryHit(term_id=terms["PRITAM SAIKIA"], case_id=case.id, reg_year=2026))
        s.add(DiscoveryHit(term_id=terms["ANIL BORA"], case_id=d.id, reg_year=2025))
        _rec(s, world, a, "EDU")
        _rec(s, world, b, "HEALTH", 0.9)
        s.add(
            CaseOwnership(
                case_id=c.id,
                office_id=world.offices["HEALTH"].id,
                role=OwnershipRole.PRIMARY,
                status=OwnershipStatus.ACTIVE,
            )
        )
        s.commit()
        ids = {"A": a.ref_no, "B": b.ref_no, "C": c.ref_no, "D": d.ref_no}
    return edu, health, terms, ids


def test_rule_endpoints_carry_discover(api, world):
    edu = login(api, "edu_admin")
    r = api.post(
        "/admin/name-patterns",
        json={"pattern": "^PRITAM", "kind": "regex", "office_code": "EDU", "discover": True},
        headers=edu,
    )
    assert r.status_code == 400 and r.json()["detail"]["code"] == "not_discoverable", r.text
    r = api.post(
        "/admin/name-patterns",
        json={"pattern": "^PRITAM", "kind": "regex", "office_code": "EDU"},
        headers=edu,
    )
    assert r.status_code == 201 and r.json()["discover"] is False and r.json()["discoverable"] is False
    rx = r.json()["id"]
    r = api.patch(f"/admin/name-patterns/{rx}", json={"discover": True}, headers=edu)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "not_discoverable"
    r = api.post("/admin/keywords", json={"keyword": "100% pass", "office_code": "EDU"}, headers=edu)
    assert r.status_code == 201 and r.json()["discover"] is False
    r = api.post("/admin/keywords", json={"keyword": "Rajib Gogoi", "office_code": "EDU"}, headers=edu)
    kw = r.json()
    assert kw["discover"] is True and kw["discovery"]["term_id"]
    r = api.patch(f"/admin/keywords/{kw['id']}", json={"discover": False}, headers=edu)
    assert r.status_code == 200 and r.json()["discover"] is False and r.json()["discovery"] is None
    with world.Session() as s:
        after = s.scalar(
            sa.select(AuditLog.after).where(
                AuditLog.entity_id == kw["id"], AuditLog.action == "keyword.update"
            )
        )
        assert after["discover"] is False
    r = api.get("/admin/keywords?discover=true", headers=edu)
    assert r.status_code == 200 and r.json()["items"] == []
    r = api.get("/admin/keywords?discover=false", headers=edu)
    assert {i["keyword"] for i in r.json()["items"]} == {"100% PASS", "RAJIB GOGOI"}


def test_terms_and_cases_are_scoped(api, world):
    edu, health, terms, refs = _setup(api, world)
    r = api.get("/admin/discovery/terms", headers=edu)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert [i["term"] for i in items] == ["PRITAM SAIKIA"]
    item = items[0]
    assert item["active"] is True and item["departments"] == ["EDU"]
    assert [(x["kind"], x["office_code"]) for x in item["rules"]] == [("prefix", "EDU")]
    assert item["years"] == {"done": 0, "waiting": len(years()), "failed": 0}
    assert item["found_last_7_days"] == 3
    r = api.get(f"/admin/discovery/terms/{terms['ANIL BORA']}/cases", headers=edu)
    assert r.status_code == 404
    root = login(api, "root")
    r = api.get("/admin/discovery/terms", headers=root)
    assert [i["term"] for i in r.json()["items"]] == ["ANIL BORA", "PRITAM SAIKIA"]
    # the term's cases for EDU: claimable by the claim rule, recommendation only for EDU
    r = api.get(f"/admin/discovery/terms/{terms['PRITAM SAIKIA']}/cases", headers=edu)
    assert r.status_code == 200, r.text
    by = {i["case"]["ref_no"]: i for i in r.json()["items"]}
    assert set(by) == {refs["A"], refs["B"], refs["C"]} and r.json()["total"] == 3
    assert by[refs["A"]]["recommendation"]["office_code"] == "EDU" and by[refs["A"]]["claimable"] is True
    assert by[refs["B"]]["recommendation"] is None and by[refs["B"]]["claimable"] is True
    assert by[refs["C"]]["owner_office_code"] == "HEALTH" and by[refs["C"]]["claimable"] is False
    assert by[refs["A"]]["reg_year"] == 2026
    r = api.get(f"/admin/discovery/terms/{terms['PRITAM SAIKIA']}/cases?only=pool", headers=edu)
    assert {i["case"]["ref_no"] for i in r.json()["items"]} == {refs["A"], refs["B"]}
    r = api.get(f"/admin/discovery/terms/{terms['PRITAM SAIKIA']}/cases?only=owned", headers=edu)
    assert {i["case"]["ref_no"] for i in r.json()["items"]} == {refs["C"]}
    r = api.get(f"/admin/discovery/terms/{terms['PRITAM SAIKIA']}/cases?only=recommended", headers=edu)
    assert {i["case"]["ref_no"] for i in r.json()["items"]} == {refs["A"]}
    r = api.get(f"/admin/discovery/terms/{terms['PRITAM SAIKIA']}/cases", headers=root)
    by = {i["case"]["ref_no"]: i for i in r.json()["items"]}
    assert (
        by[refs["B"]]["recommendation"]["office_code"] == "HEALTH"
    )  # every department's with cases.view_all
    officer = login(api, "edu_off1")
    assert api.get("/admin/discovery/terms", headers=officer).status_code == 403
    assert api.get("/admin/discovery/terms").status_code == 401


def test_a_users_request_for_years(api, world):
    edu, health, terms, refs = _setup(api, world)
    r = api.post(
        "/admin/discovery/search", json={"name": "pritam saikia", "years": [2010, 2011]}, headers=edu
    )
    assert r.status_code == 202, r.text
    assert r.json() == {
        "term_id": str(terms["PRITAM SAIKIA"]),
        "term": "PRITAM SAIKIA",
        "years": [2011, 2010],
        "queued": True,
    }
    assert "calls" not in r.text
    with world.Session() as s:
        rows = {r.ref.split("|")[2]: r for r in party_rows(s, "PRITAM SAIKIA")}
        assert {"2010", "2011"} <= set(rows) and rows["2010"].priority == 42
        audits = s.scalar(sa.select(sa.func.count()).where(AuditLog.action == "discovery.sweep"))
        assert audits == 1
    # asked again while waiting: a warning that writes nothing
    r = api.post("/admin/discovery/search", json={"name": "PRITAM SAIKIA", "years": [2011]}, headers=edu)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "searched_before", r.text
    assert r.json()["detail"]["years"] == [{"reg_year": 2011, "state": "waiting", "searched_at": None}]
    with world.Session() as s:
        for row in party_rows(s, "PRITAM SAIKIA"):
            row.status = FetchStatus.DONE
            row.finished_at = sa.func.now()
        s.commit()
    r = api.post("/admin/discovery/search", json={"name": "PRITAM SAIKIA", "years": [2011]}, headers=edu)
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["years"][0]["state"] == "searched" and detail["last_searched_at"]
    with world.Session() as s:
        assert s.scalar(sa.select(sa.func.count()).where(AuditLog.action == "discovery.sweep")) == 1
    r = api.post(
        "/admin/discovery/search", json={"name": "PRITAM SAIKIA", "years": [2011], "force": True}, headers=edu
    )
    assert r.status_code == 202
    with world.Session() as s:
        row = next(r for r in party_rows(s, "PRITAM SAIKIA") if r.ref.split("|")[2] == "2011")
        assert row.status == FetchStatus.PENDING
        audit = s.scalars(
            sa.select(AuditLog)
            .where(AuditLog.action == "discovery.sweep")
            .order_by(AuditLog.created_at.desc())
        ).first()
        assert (
            audit.after["scope"] == "request"
            and audit.after["warned"] is True
            and audit.after["force"] is True
        )
    # another department's name, a name that is no term, bad years, no function
    r = api.post("/admin/discovery/search", json={"name": "ANIL BORA", "years": [2010]}, headers=edu)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "not_a_term"
    r = api.post("/admin/discovery/search", json={"name": "NOBODY", "years": [2010]}, headers=edu)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "not_a_term"
    r = api.post("/admin/discovery/search", json={"name": "a|b=c", "years": [2010]}, headers=edu)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "not_discoverable"
    for bad in ([1900], [3000]):
        r = api.post("/admin/discovery/search", json={"name": "PRITAM SAIKIA", "years": bad}, headers=edu)
        assert r.status_code == 400 and r.json()["detail"]["code"] == "bad_years"
    officer = login(api, "edu_off1")
    r = api.post("/admin/discovery/search", json={"name": "PRITAM SAIKIA", "years": [2010]}, headers=officer)
    assert r.status_code == 403


def test_summary_and_sweep(api, world):
    edu, health, terms, refs = _setup(api, world)
    reader = login(api, "central_op")
    r = api.get("/admin/discovery", headers=reader)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["settings"]["share"] == 100 and body["window"]["discovery_calls"] == 0
    assert body["window"]["share_left"] == 100
    assert body["terms"] == {"active": 2, "inactive": 0}
    assert body["queue"]["by_kind"]["party_search"]["pending"] == 2 * len(years())
    assert body["cases"]["found"] == 4
    assert api.get("/admin/discovery", headers=login(api, "edu_off1")).status_code == 403
    assert api.get("/admin/discovery", headers=edu).status_code == 403
    r = api.post("/admin/discovery/sweep", json={}, headers=edu)
    assert r.status_code == 403
    root = login(api, "root")
    r = api.post("/admin/discovery/sweep", json={"term_id": str(terms["PRITAM SAIKIA"])}, headers=root)
    assert r.status_code == 202 and r.json() == {"terms": 1, "rows_queued": len(years())}
    with world.Session() as s:
        audit = s.scalar(sa.select(AuditLog).where(AuditLog.action == "discovery.sweep"))
        assert audit.after["scope"] == "term" and audit.actor_user_id == world.users["root"].id
    kw = api.get("/admin/keywords", headers=health).json()["items"][0]
    assert api.post(f"/admin/keywords/{kw['id']}/deactivate", headers=health).status_code == 200
    r = api.post("/admin/discovery/sweep", json={"term_id": str(terms["ANIL BORA"])}, headers=root)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "term_inactive"
    r = api.post(
        "/admin/discovery/sweep", json={"term_id": "00000000-0000-7000-8000-000000000000"}, headers=root
    )
    assert r.status_code == 404


def test_pool_found_for(api, world):
    edu, health, terms, refs = _setup(api, world)
    r = api.get("/inbox/pool?found_for=EDU", headers=edu)
    assert r.status_code == 200, r.text
    assert {i["case"]["ref_no"] for i in r.json()["items"]} == {refs["A"], refs["B"]}
    r = api.get("/inbox/pool?found_for=HEALTH", headers=edu)
    assert r.status_code == 403
    oversight = login(api, "oversight")  # cases.view_all
    r = api.get("/inbox/pool?found_for=HEALTH", headers=oversight)
    assert r.status_code == 200 and {i["case"]["ref_no"] for i in r.json()["items"]} == {refs["D"]}
    r = api.get("/inbox/pool?found_for=EDU-DSE", headers=edu)
    assert r.status_code == 400  # not a department
