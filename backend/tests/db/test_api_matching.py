"""The partial counsel-code match through the API (design partial-code-match, "API"): `PUT /admin/scoring-settings`
needs `counsel_code_partial` (422 without it), refuses an out-of-band value (400 naming the partial weight) and needs
`admin.scoring` (403 with `admin.counsel_codes` only); `GET /admin/scoring-settings` and its history carry the sixth
weight; `GET /admin/counsel-codes/unmapped` returns `partial_matches` scoped to the caller's office subtree; the
engine's partial signal reaches `GET /inbox/recommended` and the per-case scores with its `reason`."""

from __future__ import annotations

from datetime import date

import sqlalchemy as sa

from aslms.domain.ownership import CounselCode, RecommendationOrigin, ScoringSettings
from aslms.services import matching
from tests.db.test_api_inbox import api, login  # noqa: F401  (the `api` fixture)
from tests.db.test_case_visibility import entry_with_codes
from tests.db.world import make_case

WEIGHTS = {
    "counsel_code": 0.95,
    "counsel_code_partial": 0.6,
    "name_pattern": 0.8,
    "watchlist": 0.75,
    "linked_case": 0.7,
    "keyword": 0.4,
}


def _body(**over):
    weights = {**WEIGHTS, **over.pop("weights", {})}
    return {
        "weights": weights,
        "thresholds": over.pop("thresholds", {"strong": 0.85, "possible": 0.5}),
        "reason": over.pop("reason", "tuning"),
        "expected_version": over.pop("expected_version", 1),
    }


def _versions(world) -> int:
    with world.Session() as s:
        return int(s.scalar(sa.select(sa.func.count()).select_from(ScoringSettings)))


def test_scoring_settings_partial_weight(api, world, monkeypatch):  # noqa: F811
    from aslms.api.routers import matching as matching_router

    monkeypatch.setattr(matching_router, "dispatch_rescore", lambda settings: False)
    root = login(api, "root")
    r = api.get("/admin/scoring-settings", headers=root)
    assert r.status_code == 200 and r.json()["weights"]["counsel_code_partial"] == 0.6
    assert r.json()["engine_version"] == "2.1"
    without = _body()
    del without["weights"]["counsel_code_partial"]
    assert api.put("/admin/scoring-settings", json=without, headers=root).status_code == 422
    for bad in (
        _body(weights={"counsel_code_partial": 0.45}),
        _body(weights={"counsel_code_partial": 0.85}),
        _body(weights={"counsel_code_partial": 0.96}, thresholds={"strong": 0.97, "possible": 0.5}),
        _body(thresholds={"strong": 0.85, "possible": 0.7}),
    ):
        r = api.put("/admin/scoring-settings", json=bad, headers=root)
        assert r.status_code == 400 and "partial code weight" in r.text, r.text
    assert _versions(world) == 1
    # admin.counsel_codes alone reads the settings but cannot save them
    admin = login(api, "edu_admin")
    assert api.get("/admin/scoring-settings", headers=admin).status_code == 200
    assert api.put("/admin/scoring-settings", json=_body(), headers=admin).status_code == 403
    r = api.put("/admin/scoring-settings", json=_body(weights={"counsel_code_partial": 0.65}), headers=root)
    assert r.status_code == 200, r.text
    assert r.json()["version"] == 2 and r.json()["weights"]["counsel_code_partial"] == 0.65
    with world.Session() as s:  # version 1 as a pre-0027 database holds it
        s.execute(sa.text("UPDATE scoring_settings SET weight_counsel_code_partial = NULL WHERE version = 1"))
        s.commit()
    items = api.get("/admin/scoring-settings/history", headers=root).json()["items"]
    assert items[0]["weights"]["counsel_code_partial"] == 0.65
    assert "counsel_code_partial" not in items[1]["weights"]


def test_unmapped_partial_matches_scoped(api, world):  # noqa: F811
    with world.Session() as s:
        s.add(CounselCode(code="SC, EDU", office_id=world.offices["EDU"].id))
        case = make_case(s)
        entry_with_codes(s, case, ["SC, EDU, DSE"], list_date=date(2026, 10, 23))
        s.commit()
    edu = [{"code": "SC, EDU", "office_code": "EDU", "relation": "contained"}]
    for key, expected in (("root", edu), ("edu_admin", edu), ("health_admin", [])):
        r = api.get("/admin/counsel-codes/unmapped", headers=login(api, key))
        assert r.status_code == 200, r.text
        (row,) = r.json()
        assert row["code"] == "SC, EDU, DSE" and row["partial_matches"] == expected, key
    assert api.get("/admin/counsel-codes/unmapped", headers=login(api, "edu_off1")).status_code == 403


def test_recommended_and_scores_carry_the_partial_reason(api, world):  # noqa: F811
    with world.Session() as s:
        s.add(CounselCode(code="SC, EDU", office_id=world.offices["EDU"].id))
        case = make_case(s)
        entry_with_codes(s, case, ["SC, EDU, DSE"], list_date=date(2026, 10, 23))
        s.flush()
        matching.score_cases(s, [case.id], origin=RecommendationOrigin.CAUSE_LIST)
        s.commit()
        ref = case.ref_no.replace("/", "-")
    r = api.get("/inbox/recommended", headers=login(api, "edu_admin"))
    assert r.status_code == 200, r.text
    (item,) = r.json()["items"]
    assert item["band"] == "medium" and item["score"] == 0.6
    (signal,) = item["signals"]
    assert signal["kind"] == "counsel_code_partial" and signal["weight"] == 0.6
    assert signal["reason"] == "Code SC, EDU found inside SC, EDU, DSE on the cause list of 23 Oct 2026"
    assert (signal["matched"], signal["printed"], signal["relation"]) == (
        "SC, EDU",
        "SC, EDU, DSE",
        "contained",
    )
    assert api.get("/inbox/recommended", headers=login(api, "health_admin")).json()["total"] == 0
    r = api.get(f"/admin/matching/cases/{ref}/scores", headers=login(api, "root"))
    assert r.status_code == 200 and r.json()[0]["signals"][0]["reason"] == signal["reason"]


def test_counsel_codes_total_all_with_q(api, world):  # noqa: F811
    with world.Session() as s:
        for code in ("SC, EDU", "SC, EDU, DSE", "SC, HEALTH"):
            office = "HEALTH" if "HEALTH" in code else "EDU"
            s.add(CounselCode(code=code, office_id=world.offices[office].id))
        s.commit()
    root = login(api, "root")
    plain = api.get("/admin/counsel-codes", headers=root).json()
    assert plain["total"] == 3 and plain["total_all"] is None
    searched = api.get("/admin/counsel-codes", params={"q": "edu"}, headers=root).json()
    assert searched["total"] == 2 and searched["total_all"] == 3
    # the count without the search stays inside the caller's scope
    edu = api.get("/admin/counsel-codes", params={"q": "SC"}, headers=login(api, "edu_admin")).json()
    assert edu["total"] == 2 and edu["total_all"] == 2
    # wildcards match literally
    assert api.get("/admin/counsel-codes", params={"q": "S%"}, headers=root).json()["total"] == 0
