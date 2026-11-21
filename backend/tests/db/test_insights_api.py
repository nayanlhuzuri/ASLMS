"""`/insights`, `/admin/insights/*` and `/admin/title-names` end to end (design `state-insights`, "Tests",
`test_insights_api.py`): each endpoint's function (403 without), the status codes and shapes, the error codes, the
OpenAPI names and the data-health block."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from aslms.api.main import create_app
from aslms.core.config import Settings
from aslms.domain.cases import CaseStatus
from aslms.domain.insights import InsightGroup
from aslms.services import insights_facts
from tests.db import insights_support as ins
from tests.db.report_support import claim
from tests.db.workflow_support import login

STATE = ("THE STATE OF ASSAM",)


@pytest.fixture()
def api(world):
    settings = Settings(
        _env_file=None,
        aslms_jwt_secret="test-secret-of-at-least-thirty-two-characters",
        aslms_access_token_minutes=5,
    )
    with TestClient(create_app(settings, world.Session)) as client:
        yield client


def _data(world):
    with world.Session() as s:
        a = ins.case(s, respondents=(*STATE, "THE SECRETARY, EDUCATION DEPARTMENT"))
        claim(s, world, a)
        b = ins.case(s, respondents=("THE SECRETARY, TEA TRIBES DEPARTMENT",))
        ins.build(s, a, b)
        s.commit()
        return a, b


def test_functions_and_scopes(api, world):
    _data(world)
    assert api.get("/insights").status_code == 401
    officer = login(api, "edu_off1")
    for path in ("/insights", "/insights/scopes", "/insights/cases", "/insights/fields", "/insights/export"):
        assert api.get(path, headers=officer).status_code == 403, path
    over = login(api, "oversight")
    assert api.get("/insights/scopes", headers=over).json() == {
        "state": True,
        "departments": [],
        "default": {"scope": "state", "department": None},
    }
    admin = login(api, "edu_admin")
    scopes = api.get("/insights/scopes", headers=admin).json()
    assert scopes["state"] is False and scopes["departments"] == [{"code": "EDU", "name": "Education"}]
    r = api.get("/insights?scope=state", headers=admin)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "no_insights_function"
    r = api.get("/insights?scope=department&department=HEALTH", headers=admin)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "department_not_yours"
    assert api.get("/insights", headers=admin).json()["scope"]["department"]["code"] == "EDU"


def test_overview_cases_fields_shapes(api, world):
    a, _ = _data(world)
    root = login(api, "root")
    r = api.get("/insights", headers=root)
    assert r.status_code == 200
    body = r.json()
    assert body["scope"] == {"kind": "state", "department": None}
    assert set(body["headline"]) >= {"cases", "state_cases", "contempt", "not_claimed", "applications_inside"}
    assert body["coverage"]["court"] == "Gauhati High Court" and body["coverage"]["facts_waiting"] == 0
    assert body["departments"][0]["code"] == "EDU" and body["accountability"]["scorecard"] is not None
    assert (
        body["headline"]["cases"] == 1 and body["unmapped_named"] == 0
    )  # the unmapped case is not a State case
    every = api.get("/insights?state_only=false", headers=root).json()
    assert every["headline"]["cases"] == 2 and every["unmapped_named"] == 1
    r = api.get("/insights/cases?sort=registered&page=1", headers=root)
    page = r.json()
    assert r.status_code == 200 and page["page_size"] == 20 and page["sort"] == "registered"
    item = next(i for i in page["items"] if i["case"]["id"] == str(a.id))
    assert item["who"]["kind"] == "office" and item["kind"] == {"code": "writ", "label": "Writ Petition"}
    assert item["departments_named"] == [{"code": "EDU", "name": "Education"}]
    fields = api.get("/insights/fields", headers=root).json()
    assert len(fields) == 34 and fields[0]["key"] == "case_no" and fields[0]["default"] is True


def test_error_codes(api, world):
    root = login(api, "root")
    r = api.get("/insights?next=soon", headers=root)
    assert r.status_code == 400 and r.json()["detail"] == {
        "code": "bad_filter",
        "message": "next is not a known value",
        "param": "next",
    }
    r = api.get("/insights?date_of=registration&from=2026-03-01&to=2026-01-01", headers=root)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "bad_dates"
    r = api.get("/insights/cases?sort=cnr", headers=root)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "bad_sort"
    assert api.get("/insights/export?format=csv", headers=root).status_code == 422


def test_groups_admin_endpoints(api, world):
    with world.Session() as s:
        ins.case_types(s)
        s.commit()
    admin = login(api, "edu_admin")
    assert api.get("/admin/insights/groups?kind=subject", headers=admin).status_code == 403
    root = login(api, "root")
    groups = api.get("/admin/insights/groups?kind=family", headers=root).json()
    assert len(groups) == 20 and {g["code"] for g in groups if g["is_reserved"]} == {
        "contempt",
        "ia",
        "other",
    }
    assert api.get("/admin/insights/groups?kind=x", headers=root).json()["detail"]["code"] == "bad_kind"
    r = api.post(
        "/admin/insights/groups", json={"kind": "subject", "code": "forest", "label": "Forest"}, headers=root
    )
    assert r.status_code == 201
    r = api.post(
        "/admin/insights/groups",
        json={"kind": "subject", "code": "forest", "label": "Forest 2"},
        headers=root,
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "code_taken"
    with world.Session() as s:
        ia = s.scalar(sa.select(InsightGroup).where(InsightGroup.kind == "family", InsightGroup.code == "ia"))
    r = api.patch(f"/admin/insights/groups/{ia.id}", json={"is_active": False}, headers=root)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "reserved_group"
    r = api.put(
        "/admin/insights/categories", json={"changes": [{"code": 10023, "group": "forest"}]}, headers=root
    )
    assert r.status_code == 200 and r.json() == [
        {"code": 10023, "label": r.json()[0]["label"], "group": "forest", "cases": 0, "pending": 0}
    ]
    cats = api.get("/admin/insights/categories?group=forest", headers=root).json()
    assert [c["code"] for c in cats] == [10023]
    assert (
        api.get("/admin/insights/categories?sort=nope", headers=root).json()["detail"]["code"] == "bad_sort"
    )
    types = api.get("/admin/insights/case-types?q=WA", headers=root).json()
    wa = next(t for t in types if t["code"] == 112)
    r = api.put(
        "/admin/insights/case-types",
        json={"changes": [{"case_type_id": wa["id"], "group": "review"}]},
        headers=root,
    )
    assert r.status_code == 200 and r.json()[0]["group"] == "review"


def test_title_names_endpoints(api, world):
    _data(world)
    admin = login(api, "edu_admin")
    r = api.get("/admin/title-names/unmapped", headers=admin)
    assert r.status_code == 200 and r.json()["items"][0]["phrase"] == "TEA TRIBES"
    r = api.post("/admin/title-names", json={"office_code": "EDU-DSE", "phrase": "tea tribes"}, headers=admin)
    assert (
        r.status_code == 201 and r.json()["phrase"] == "TEA TRIBES" and r.json()["department_code"] == "EDU"
    )
    assert r.json()["insights_refresh_dispatched"] is False  # no broker in the tests
    rid = r.json()["id"]
    r = api.post("/admin/title-names", json={"office_code": "EDU", "phrase": "TEA TRIBES"}, headers=admin)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "phrase_taken"
    r = api.post("/admin/title-names", json={"office_code": "EDU", "phrase": "ab"}, headers=admin)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "bad_phrase"
    assert (
        api.post(
            "/admin/title-names", json={"office_code": "HEALTH", "phrase": "XYZ"}, headers=admin
        ).status_code
        == 403
    )
    assert (
        api.patch(f"/admin/title-names/{rid}", json={"office_code": "EDU"}, headers=admin).json()[
            "office_code"
        ]
        == "EDU"
    )
    assert api.post(f"/admin/title-names/{rid}/deactivate", headers=admin).json()["is_active"] is False
    assert api.get("/admin/title-names?active=false", headers=admin).json()["total"] == 1
    assert api.post(f"/admin/title-names/{rid}/reactivate", headers=admin).json()["is_active"] is True
    health = login(api, "health_admin")
    assert (
        api.patch(f"/admin/title-names/{rid}", json={"office_code": "HEALTH"}, headers=health).status_code
        == 404
    )
    assert api.get("/admin/title-names", headers=login(api, "edu_off1")).status_code == 403


def test_openapi_names(api):
    spec = api.app.openapi()  # /openapi.json is 404 outside dev
    for path in (
        "/insights",
        "/insights/scopes",
        "/insights/cases",
        "/insights/fields",
        "/insights/export",
        "/admin/insights/groups",
        "/admin/insights/categories",
        "/admin/insights/case-types",
        "/admin/title-names",
        "/admin/title-names/unmapped",
    ):
        assert path in spec["paths"], path
    params = {p["name"] for p in spec["paths"]["/insights"]["get"]["parameters"]}
    assert {
        "scope",
        "department",
        "status",
        "state_only",
        "include_ia",
        "next",
        "from",
        "to",
        "date_of",
    } <= params
    assert (
        "InsightsOut" in spec["components"]["schemas"]
        and "InsightsStatusOut" in spec["components"]["schemas"]
    )


def test_data_health_block(api, world):
    _data(world)
    r = api.get("/admin/data-health", headers=login(api, "root"))
    assert r.status_code == 200
    block = r.json()["insights"]
    assert block["live_cases"] == 2 and block["facts_built"] == 2 and block["waiting"] == 0
    assert block["reader_version"] == "2" and block["unmapped_phrases"] == 1
    assert set(block["state_bases"]) == {"party", "officer", "counsel", "title", "writ"}


def test_data_health_insights_block_has_named_rescore_waiting(api, world):
    """Design cause-title-signal-review-advisories, decision 12: the cases waiting for the drain, a count only."""
    _data(world)  # the claimed case names EDUCATION: its built row is marked
    headers = login(api, "root")
    block = api.get("/admin/data-health", headers=headers).json()["insights"]
    assert block["named_rescore_waiting"] == 1
    insights_facts.rescore_marked(world.Session)
    block = api.get("/admin/data-health", headers=headers).json()["insights"]
    assert block["named_rescore_waiting"] == 0
    spec = api.get("/openapi.json").json()["components"]["schemas"]["InsightsStatusOut"]
    assert "named_rescore_waiting" in spec["required"]


def test_timeout_answers_503(api, world, monkeypatch):
    from aslms.services import insights

    def slow(*args, **kwargs):
        raise insights.InsightsTimeout(insights.InsightsTimeout.message)

    monkeypatch.setattr(insights, "overview", slow)
    r = api.get("/insights", headers=login(api, "root"))
    assert r.status_code == 503 and r.json()["detail"]["code"] == "insights_timeout"


# ------------------------------------------------------------------------------------------------ review advisories
# design state-insights-review-advisories: the `dept` refusal end to end (decision 3), the group writes' answers and
# the sort-order bound (decision 6), and a listed phrase that can be mapped as it stands (decision 4)


def test_dept_filter_refused_outside_state_scope_api(api, world):
    _data(world)
    admin = login(api, "edu_admin")
    for path in ("/insights", "/insights/cases", "/insights/export"):
        for query in ("dept=HEALTH", "dept=HEALTH&band=likely"):
            r = api.get(f"{path}?scope=department&department=EDU&{query}", headers=admin)
            assert r.status_code == 400, (path, query)
            assert r.json()["detail"]["code"] == "bad_filter" and r.json()["detail"]["param"] == "dept"
    over = login(api, "oversight")  # a State-wide holder's department view
    r = api.get("/insights?scope=department&department=EDU&dept=EDU", headers=over)
    assert r.status_code == 400 and r.json()["detail"]["param"] == "dept"
    root = login(api, "root")
    before = api.get("/insights?scope=state&dept=EDU", headers=root)
    assert before.status_code == 200 and before.json()["headline"]["cases"] == 1
    assert api.get("/insights?scope=state&dept=EDU&band=claimed", headers=root).status_code == 200


def test_group_writes_answer_real_counts(api, world):
    with world.Session() as s:
        cases = [ins.case(s, respondents=STATE) for _ in range(3)]
        cases[2].status = CaseStatus.DISPOSED
        ins.build(s, *cases)
        s.commit()
    root = login(api, "root")
    r = api.post(
        "/admin/insights/groups",
        json={"kind": "family", "code": "writs_all", "label": "All Writs"},
        headers=root,
    )
    assert r.status_code == 201
    created = r.json()
    listed = {g["id"]: g for g in api.get("/admin/insights/groups?kind=family", headers=root).json()}
    assert created == listed[created["id"]] and created["cases"] == 0
    types = api.get("/admin/insights/case-types?q=WP", headers=root).json()
    wp = next(t for t in types if t["code"] == 111)
    r = api.put(
        "/admin/insights/case-types",
        json={"changes": [{"case_type_id": wp["id"], "group": "writs_all"}]},
        headers=root,
    )
    assert r.status_code == 200
    line = r.json()[0]
    assert line["cases"] == 3 and line["pending"] == 2 and line["full_name"] == "Writ Petition"
    assert line == next(
        t for t in api.get("/admin/insights/case-types", headers=root).json() if t["id"] == wp["id"]
    )
    r = api.patch(f"/admin/insights/groups/{created['id']}", json={"label": "Every Writ"}, headers=root)
    assert r.status_code == 200
    patched = r.json()
    listed = {g["id"]: g for g in api.get("/admin/insights/groups?kind=family", headers=root).json()}
    assert patched == listed[created["id"]] and (
        patched["members"],
        patched["cases"],
        patched["pending"],
    ) == (
        1,
        3,
        2,
    )
    r = api.put(
        "/admin/insights/categories", json={"changes": [{"code": 10023, "group": "education"}]}, headers=root
    )
    assert r.status_code == 200
    cat = r.json()[0]
    assert (cat["cases"], cat["pending"]) == (3, 2)
    assert cat == next(
        c for c in api.get("/admin/insights/categories", headers=root).json() if c["code"] == 10023
    )


def test_sort_order_bounds_api(api, world):
    with world.Session() as s:
        ins.case_types(s)
        s.commit()
    root = login(api, "root")
    for value in (-1, 10_001, 2**40, 99_999_999_999):
        r = api.post(
            "/admin/insights/groups",
            json={"kind": "subject", "code": "forest", "label": "Forest", "sort_order": value},
            headers=root,
        )
        assert r.status_code == 400 and r.json()["detail"]["code"] == "bad_sort_order", value
    r = api.post(
        "/admin/insights/groups",
        json={"kind": "subject", "code": "forest", "label": "Forest", "sort_order": 10_000},
        headers=root,
    )
    assert r.status_code == 201 and r.json()["sort_order"] == 10_000
    gid = r.json()["id"]
    r = api.patch(f"/admin/insights/groups/{gid}", json={"sort_order": 99_999_999_999}, headers=root)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "bad_sort_order"
    assert (
        api.patch(f"/admin/insights/groups/{gid}", json={"sort_order": 0}, headers=root).json()["sort_order"]
        == 0
    )


def test_listed_phrase_can_be_mapped(api, world):
    with world.Session() as s:
        a = ins.case(s, respondents=("THE CHIEF ENGINEER, P.W.D.'S DEPARTMENT",))
        b = ins.case(s, respondents=("THE CHIEF ENGINEER, P.W.D.’S DEPARTMENT",))
        insights_facts.refresh(s)
        s.commit()
    admin = login(api, "root")
    items = api.get("/admin/title-names/unmapped", headers=admin).json()["items"]
    listed = [i for i in items if i["phrase"].startswith("P.W.D")]
    assert [i["phrase"] for i in listed] == ["P.W.D.S"] and listed[0]["cases"] == 2
    r = api.post(
        "/admin/title-names", json={"office_code": "HEALTH", "phrase": listed[0]["phrase"]}, headers=admin
    )
    assert r.status_code == 201 and r.json()["phrase"] == "P.W.D.S"
    with world.Session() as s:
        insights_facts.refresh(s)
        s.commit()
        health = world.office(s, "HEALTH").id
        assert ins.fact(s, a).named_title_department_ids == [health]
        assert ins.fact(s, b).named_title_department_ids == [health]
    items = api.get("/admin/title-names/unmapped", headers=admin).json()["items"]
    assert not [i for i in items if i["phrase"].startswith("P.W.D")]
