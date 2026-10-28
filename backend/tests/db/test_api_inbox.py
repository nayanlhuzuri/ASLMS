"""The inbox, ownership and matching-rule endpoints end to end (design recommend-and-claim, "API" tests):
the Recommended tab and its scope, the Claimed tab by role with Active / Disposed, the pool and its filters,
transfers, claim by id / ref_no / CNR, the ownership view's visibility, take-over and stop-watching, the
scoring settings, the rule endpoints and the 401 without a token."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from aslms.api.main import create_app
from aslms.api.routers import matching as matching_router
from aslms.core.clock import today_ist
from aslms.core.config import Settings
from aslms.domain.cases import CaseStatus
from aslms.domain.causelists import Causelist, CauselistEntry, EntrySource, ListSource, ListType
from aslms.domain.courts import Court
from aslms.domain.events import AuditLog
from aslms.domain.ownership import (
    CaseOfficeScore,
    Recommendation,
    RecommendationOrigin,
    RecommendationStatus,
    ScoreBand,
)
from aslms.services.cases import refresh_search_vector
from tests.db.auth_support import bearer
from tests.db.world import OTHER_BENCH, PW, SINGLE_BENCH, USERS, add_listing, make_case


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


def recommend(s, world, case, code, *, score=0.95, band=ScoreBand.HIGH, signals=True):
    rec = Recommendation(
        case_id=case.id,
        office_id=world.offices[code].id,
        score=score,
        band=band,
        origin=RecommendationOrigin.CAUSE_LIST,
        actor_name="matching",
    )
    s.add(rec)
    if signals:
        s.add(
            CaseOfficeScore(
                case_id=case.id,
                office_id=world.offices[code].id,
                score=score,
                signals=[
                    {
                        "kind": "counsel_code",
                        "rule_id": None,
                        "rule_office_code": code,
                        "weight": score,
                        "matched": f"SC, {code}",
                        "where": "causelist_entry",
                        "ref": {"list_date": "2025-01-06", "sr_no": 1},
                    }
                ],
                engine_version="1.1",
            )
        )
    s.flush()
    return rec


def ids(payload) -> list[str]:
    return [str(i["case"]["id"]) for i in payload["items"]]


# ------------------------------------------------------------------------------------------------ recommended


def test_recommended_tab_scope_and_order(api, world):
    with world.Session() as s:
        a = make_case(s, next_hearing=date(2026, 10, 20))
        b = make_case(s)
        c = make_case(s)
        recommend(s, world, a, "EDU", score=0.95, band=ScoreBand.HIGH)
        recommend(s, world, b, "EDU", score=0.6, band=ScoreBand.MEDIUM)
        recommend(s, world, c, "HEALTH")
        s.commit()
        a_id, b_id = str(a.id), str(b.id)
    admin = login(api, "edu_admin")
    r = api.get("/inbox/recommended", headers=admin)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2 and ids(body) == [a_id, b_id]
    assert body["items"][0]["band"] == "high" and body["items"][0]["signals"][0]["kind"] == "counsel_code"
    assert body["items"][0]["case"]["next_hearing"]["date"] == "2026-10-20"
    assert body["items"][0]["current_owner_code"] is None
    assert api.get("/inbox/recommended?band=medium", headers=admin).json()["total"] == 1
    assert api.get("/inbox/recommended?office=HEALTH", headers=admin).status_code == 403
    # a State-wide reader reads any department, read-only
    oversight = login(api, "oversight")
    r = api.get("/inbox/recommended?office=EDU", headers=oversight)
    assert r.status_code == 200 and r.json()["total"] == 2
    assert api.get("/inbox/recommended", headers=oversight).status_code == 400  # office required
    assert api.post(f"/cases/{a_id}/claim", json={}, headers=oversight).status_code == 403
    # a department officer without cases.claim cannot read the Recommended tab
    assert api.get("/inbox/recommended", headers=login(api, "edu_off1")).status_code == 403


# ------------------------------------------------------------------------------------------------ claimed


def test_claimed_tab_by_role_and_case_state(api, world):
    with world.Session() as s:
        p1, p2 = make_case(s), make_case(s)
        p3 = make_case(s, status=CaseStatus.DISPOSED)
        s.commit()
        off1 = str(world.users["edu_off1"].id)
        off2 = str(world.users["edu_off2"].id)
        p1_id, p2_id, p3_id = str(p1.id), str(p2.id), str(p3.id)
    admin = login(api, "edu_admin")
    r = api.post(
        f"/cases/{p1_id}/claim", json={"unit_code": "EDU-DSE", "officer_user_id": off1}, headers=admin
    )
    assert r.status_code == 201, r.text
    assert r.json()["role"] == "primary" and r.json()["unit"]["code"] == "EDU-DSE"
    assert r.json()["officer"]["id"] == off1 and r.json()["allotted_at"] is not None
    assert api.post(f"/cases/{p2_id}/claim", json={"officer_user_id": off2}, headers=admin).status_code == 201
    assert api.post(f"/cases/{p3_id}/claim", json={}, headers=admin).status_code == 201
    # the department admin sees the whole department; Active by default
    assert sorted(ids(api.get("/inbox/claimed", headers=admin).json())) == sorted([p1_id, p2_id])
    assert ids(api.get("/inbox/claimed?case_state=disposed", headers=admin).json()) == [p3_id]
    assert api.get("/inbox/claimed?case_state=all", headers=admin).json()["total"] == 3
    assert api.get("/inbox/claimed?case_state=nope", headers=admin).status_code == 400
    assert ids(api.get("/inbox/claimed?unit=EDU-DSE", headers=admin).json()) == [p1_id]
    assert ids(api.get(f"/inbox/claimed?officer_user_id={off2}", headers=admin).json()) == [p2_id]
    # a directorate user sees the cases allotted to its directorate; officers the cases allotted to them
    assert ids(api.get("/inbox/claimed", headers=login(api, "dse_user")).json()) == [p1_id]
    assert api.get("/inbox/claimed", headers=login(api, "dhe_user")).json()["total"] == 0
    assert ids(api.get("/inbox/claimed", headers=login(api, "edu_off1")).json()) == [p1_id]
    assert ids(api.get("/inbox/claimed", headers=login(api, "edu_off2")).json()) == [p2_id]
    # another department sees none of EDU's cases (visibility)
    health = login(api, "health_admin")
    assert api.get("/inbox/claimed", headers=health).json()["total"] == 0
    assert api.get("/inbox/claimed?office=EDU", headers=health).status_code == 403
    assert api.get("/inbox/claimed?office=EDU", headers=login(api, "oversight")).json()["total"] == 2
    # counts agree with the lists
    counts = api.get("/inbox/counts", headers=admin).json()["departments"][0]
    assert counts["claimed_active"] == 2 and counts["claimed_disposed"] == 1
    assert counts["recommended_high"] == 0 and counts["transfers_in_open"] == 0
    counts = api.get("/inbox/counts", headers=login(api, "edu_off1")).json()["departments"][0]
    assert counts["claimed_active"] == 1 and counts["recommended_high"] is None
    assert counts["pool_with_hearing_7d"] is None and counts["transfers_in_open"] is None


# ------------------------------------------------------------------------------------------------ pool


def test_pool_excludes_owned_and_filters(api, world):
    with world.Session() as s:
        q1 = make_case(s, pet="RAM KUMAR", next_hearing=today_ist() + timedelta(days=3))
        q2 = make_case(s)
        q3 = make_case(s)
        q4 = make_case(s, pet="GAUHATI UNIVERSITY")
        q5 = make_case(s)
        q6 = make_case(s)
        # q4: dismissed by EDU (stays in the pool); q5: a weak score only
        rec = recommend(s, world, q4, "EDU", score=0.6, band=ScoreBand.MEDIUM)
        rec.status = RecommendationStatus.DISMISSED
        s.add(
            CaseOfficeScore(
                case_id=q5.id, office_id=world.offices["EDU"].id, score=0.4, signals=[], engine_version="1.1"
            )
        )
        # q6 is listed with the State's education counsel code
        court = s.scalar(sa.select(Court).where(Court.est_code == "GAHC01"))
        cl = Causelist(
            court_id=court.id,
            list_date=date(2025, 1, 6),
            list_type=ListType.DAILY,
            source=ListSource.GHC_WEBSITE,
        )
        s.add(cl)
        s.flush()
        s.add(
            CauselistEntry(
                causelist_id=cl.id,
                sr_no=1,
                case_id=q6.id,
                cnr=q6.cnr,
                counsel_codes=["SC,EDU"],
                source=EntrySource.PDF_PARSE,
                petitioner_text="X",
                respondent_text="THE STATE OF ASSAM",
            )
        )
        refresh_search_vector(s, [q1.id, q4.id])  # words are the Search box's (portal-filters, decision 3)
        s.commit()
        q = {k: str(v.id) for k, v in dict(q1=q1, q2=q2, q3=q3, q4=q4, q5=q5, q6=q6).items()}
    root = login(api, "root")
    admin = login(api, "edu_admin")
    health = login(api, "health_admin")
    r = api.post("/admin/counsel-codes", json={"code": "SC,EDU", "office_code": "EDU"}, headers=admin)
    assert r.status_code == 201, r.text
    # q2 claimed by EDU; q3 claimed by EDU and transferred to HEALTH: both leave the pool for good
    assert api.post(f"/cases/{q['q2']}/claim", json={}, headers=admin).status_code == 201
    assert api.post(f"/cases/{q['q3']}/claim", json={}, headers=admin).status_code == 201
    r = api.post(
        f"/cases/{q['q3']}/transfers", json={"to_office_code": "HEALTH", "reason": "theirs"}, headers=admin
    )
    assert r.status_code == 201, r.text
    trf = r.json()
    assert trf["ref_no"].startswith("ASLMS/EDU/TRF/") and trf["status"] == "requested"
    inbox_in = api.get("/inbox/transfers?direction=in", headers=health).json()
    assert inbox_in["total"] == 1 and inbox_in["items"][0]["id"] == trf["id"]
    assert api.get("/inbox/transfers?direction=out", headers=health).json()["total"] == 0
    assert api.get("/inbox/counts", headers=health).json()["departments"][0]["transfers_in_open"] == 1
    assert api.get("/inbox/transfers", headers=login(api, "health_off")).status_code == 403
    r = api.post(f"/transfers/{trf['id']}/accept", json={"note": "ok"}, headers=health)
    assert r.status_code == 200 and r.json()["status"] == "accepted" and r.json()["decision_note"] == "ok"
    assert api.get("/inbox/counts", headers=health).json()["departments"][0]["transfers_in_open"] == 0
    # the pool
    pool = api.get("/inbox/pool", headers=admin).json()
    assert set(ids(pool)) == {q["q1"], q["q4"], q["q5"], q["q6"]}
    assert ids(pool)[0] == q["q1"]  # the next hearing first
    by_id = {str(i["case"]["id"]): i for i in pool["items"]}
    assert by_id[q["q4"]]["dismissed_by"] == ["EDU"] and by_id[q["q4"]]["best_score"] == 0.6
    assert by_id[q["q5"]]["best_score"] == 0.4 and by_id[q["q5"]]["best_office_code"] == "EDU"
    assert by_id[q["q6"]]["case"]["last_listed_on"] == "2025-01-06"
    assert ids(api.get("/inbox/pool?q=UNIVERSITY", headers=admin).json()) == [q["q4"]]
    assert api.get("/inbox/pool?q=UN", headers=admin).status_code == 400
    assert ids(api.get("/inbox/pool?state_party=true", headers=admin).json()) == [q["q6"]]
    assert set(ids(api.get("/inbox/pool?min_score=0.5", headers=admin).json())) == {q["q4"]}
    assert ids(api.get("/inbox/pool?listed_from=2025-01-01&listed_to=2025-01-31", headers=admin).json()) == [
        q["q6"]
    ]
    assert api.get("/inbox/pool", headers=root).json()["total"] == 4
    assert api.get("/inbox/pool", headers=login(api, "central_op")).json()["total"] == 4
    assert api.get("/inbox/pool", headers=login(api, "health_off")).status_code == 403
    assert api.get("/inbox/counts", headers=admin).json()["departments"][0]["pool_with_hearing_7d"] == 1


# ------------------------------------------------------------------------------------------------ claim refs, ownership view


def test_claim_by_ref_forms_and_ownership_visibility(api, world):
    with world.Session() as s:
        x, y, z, pool_case = make_case(s), make_case(s), make_case(s), make_case(s)
        s.commit()
        x_id, y_ref, z_cnr, pool_id = str(x.id), y.ref_no.replace("/", "-"), z.cnr, str(pool_case.id)
    admin = login(api, "edu_admin")
    health = login(api, "health_admin")
    assert api.post(f"/cases/{x_id}/claim", json={}, headers=admin).status_code == 201
    assert api.post(f"/cases/{y_ref}/claim", json={}, headers=admin).status_code == 201
    assert api.post(f"/cases/{z_cnr}/claim", json={}, headers=admin).status_code == 201
    assert api.post("/cases/ASLMS-GHC-CASE-2099-999999/claim", json={}, headers=admin).status_code == 404
    r = api.post(f"/cases/{x_id}/claim", json={}, headers=admin)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "already_claimed"
    # the ownership view: the owner sees it, a department with no recommendation does not, State-wide does
    assert api.get(f"/cases/{x_id}/ownership", headers=health).status_code == 404
    assert api.post(f"/cases/{x_id}/claim", json={}, headers=health).status_code == 404
    r = api.get(f"/cases/{x_id}/ownership", headers=admin)
    assert r.status_code == 200 and r.json()["primary"]["office_code"] == "EDU"
    assert r.json()["watchers"] == [] and r.json()["open_transfer"] is None
    assert api.get(f"/cases/{x_id}/ownership", headers=login(api, "oversight")).status_code == 200
    r = api.get(f"/cases/{pool_id}/ownership", headers=admin)
    assert r.status_code == 200 and r.json()["primary"] is None
    assert api.get(f"/cases/{pool_id}/ownership", headers=login(api, "edu_off1")).status_code == 404
    # dismiss and suggest through the API
    with world.Session() as s:
        d = make_case(s)
        recommend(s, world, d, "EDU", score=0.9)
        s.commit()
        d_id = str(d.id)
    r = api.post(f"/cases/{d_id}/dismiss", json={"reason": "not ours"}, headers=admin)
    assert r.status_code == 200 and r.json()["status"] == "dismissed" and r.json()["reason"] == "not ours"
    assert api.post(f"/cases/{d_id}/dismiss", json={}, headers=admin).status_code == 404
    r = api.post(f"/cases/{d_id}/suggest", json={"office_code": "HEALTH", "reason": "medical"}, headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["own"] is None and r.json()["target"]["origin"] == "suggestion"
    assert r.json()["target_already_recommended"] is False
    assert ids(api.get("/inbox/recommended", headers=health).json()) == [d_id]
    assert (
        api.post(f"/cases/{d_id}/suggest", json={"office_code": "HEALTH"}, headers=admin).status_code == 422
    )


# ------------------------------------------------------------------------------------------------ take over, stop watching


def test_take_over_and_stop_watching(api, world):
    with world.Session() as s:
        t1, t2 = make_case(s), make_case(s)
        s.commit()
        off1, off2 = str(world.users["edu_off1"].id), str(world.users["edu_off2"].id)
        t1_id, t2_id = str(t1.id), str(t2.id)
    admin = login(api, "edu_admin")
    assert api.post(f"/cases/{t1_id}/claim", json={"officer_user_id": off1}, headers=admin).status_code == 201
    assert api.post(f"/cases/{t2_id}/claim", json={}, headers=admin).status_code == 201
    r = api.post(
        f"/cases/{t1_id}/take-over", json={"reason": "holder on leave"}, headers=login(api, "edu_off2")
    )
    assert r.status_code == 200, r.text
    assert r.json()["officer"]["id"] == off2 and r.json()["taken_from"]["id"] == off1
    assert api.post(f"/cases/{t1_id}/take-over", json={}, headers=login(api, "health_off")).status_code == 404
    r = api.post(f"/cases/{t2_id}/take-over", json={}, headers=login(api, "edu_off1"))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_allotted"
    assert (
        api.post(f"/cases/{t1_id}/take-over", json={}, headers=login(api, "edu_reviewer")).status_code == 403
    )
    # stop watching: never for the primary; a watcher may
    r = api.post(f"/cases/{t1_id}/stop-watching", json={"reason": "done"}, headers=admin)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "primary_cannot_release"
    with world.Session() as s:
        recommend(s, world, s.get(type(t1), t1.id), "HEALTH", signals=False)
        s.commit()
    health = login(api, "health_admin")
    r = api.post(f"/cases/{t1_id}/claim", json={}, headers=health)
    assert r.status_code == 201 and r.json()["role"] == "watcher"
    assert api.post(f"/cases/{t1_id}/stop-watching", json={}, headers=health).status_code == 422
    r = api.post(f"/cases/{t1_id}/stop-watching", json={"reason": "not needed"}, headers=health)
    assert (
        r.status_code == 200
        and r.json()["status"] == "released"
        and r.json()["release_reason"] == "not needed"
    )
    assert api.post(f"/cases/{t1_id}/release", json={"reason": "x"}, headers=admin).status_code in (404, 405)
    with world.Session() as s:
        actions = list(
            s.scalars(
                sa.select(AuditLog.action)
                .where(AuditLog.case_id == t1.id)
                .order_by(AuditLog.created_at, AuditLog.id)
            )
        )
    assert actions == [
        "ownership.claim",
        "ownership.allot",
        "ownership.take_over",
        "ownership.claim",
        "ownership.unwatch",
    ]


# ------------------------------------------------------------------------------------------------ scoring settings


def test_scoring_settings_endpoints(api, world, monkeypatch):
    root = login(api, "root")
    admin = login(api, "edu_admin")
    r = api.get("/admin/scoring-settings", headers=root)
    assert r.status_code == 200 and r.json()["version"] == 1 and r.json()["engine_version"] == "2.1"
    assert r.json()["thresholds"] == {"strong": 0.85, "possible": 0.5}
    assert api.get("/admin/scoring-settings", headers=admin).status_code == 200
    assert api.get("/admin/scoring-settings", headers=login(api, "edu_off1")).status_code == 403
    body = {
        "weights": {
            "counsel_code": 0.95,
            "name_pattern": 0.8,
            "watchlist": 0.75,
            "linked_case": 0.7,
            "keyword": 0.4,
            "counsel_code_partial": 0.6,
        },
        "thresholds": {"strong": 0.96, "possible": 0.5},
        "reason": "stricter strong band",
        "expected_version": 1,
    }
    assert api.put("/admin/scoring-settings", json=body, headers=admin).status_code == 403
    calls = []
    monkeypatch.setattr(matching_router, "dispatch_rescore", lambda settings: calls.append(1) or True)
    r = api.put("/admin/scoring-settings", json=body, headers=root)
    assert r.status_code == 200, r.text
    assert r.json()["version"] == 2 and r.json()["changed"] is True and r.json()["rescore_dispatched"] is True
    assert r.json()["applies_within_minutes"] == 15 and r.json()["engine_version"] == "2.2"
    assert r.json()["updated_by"]["full_name"] == "Root" and len(calls) == 1
    assert api.put("/admin/scoring-settings", json=body, headers=root).status_code == 409  # stale version
    r = api.put("/admin/scoring-settings", json={**body, "expected_version": 2}, headers=root)
    assert (
        r.status_code == 200 and r.json()["changed"] is False and r.json()["version"] == 2 and len(calls) == 1
    )
    bad = {**body, "expected_version": 2, "thresholds": {"strong": 0.5, "possible": 0.6}}
    assert api.put("/admin/scoring-settings", json=bad, headers=root).status_code == 400
    r = api.get("/admin/scoring-settings/history", headers=root)
    assert r.status_code == 200 and r.json()["total"] == 2
    assert [i["version"] for i in r.json()["items"]] == [2, 1] and r.json()["items"][1][
        "valid_to"
    ] is not None
    assert api.get("/admin/scoring-settings/history", headers=admin).status_code == 403


# ------------------------------------------------------------------------------------------------ rules


def test_rule_endpoints(api, world):
    root = login(api, "root")
    admin = login(api, "edu_admin")
    assert api.get("/inbox/recommended").status_code == 401
    r = api.post("/admin/counsel-codes", json={"code": "sc , edu", "office_code": "EDU"}, headers=admin)
    assert r.status_code == 201, r.text
    code = r.json()
    assert code["code"] == "SC, EDU" and code["effective_weight"] == 0.95 and code["weight_override"] is None
    assert code["applies_within_minutes"] == 15 and code["office"]["code"] == "EDU"
    assert (
        api.post(
            "/admin/counsel-codes", json={"code": "SC,EDU", "office_code": "EDU"}, headers=admin
        ).status_code
        == 409
    )
    assert (
        api.post(
            "/admin/counsel-codes", json={"code": "SC, HLT", "office_code": "HEALTH"}, headers=admin
        ).status_code
        == 403
    )
    generic = {"code": "GA, ASSAM", "office_code": "GOA", "is_generic_state": True}
    assert api.post("/admin/counsel-codes", json=generic, headers=admin).status_code == 403
    assert (
        api.post(
            "/admin/counsel-codes",
            json={"code": "SC, DSE", "office_code": "EDU-DSE", "weight": 0.9},
            headers=admin,
        ).status_code
        == 403
    )
    r = api.post("/admin/counsel-codes", json=generic, headers=root)
    assert r.status_code == 201 and r.json()["is_generic_state"] is True
    generic_id = r.json()["id"]
    r = api.post(
        "/admin/counsel-codes", json={"code": "SC, HLT", "office_code": "HEALTH", "weight": 0.9}, headers=root
    )
    assert r.status_code == 201 and r.json()["effective_weight"] == 0.9 and r.json()["weight_override"] == 0.9
    health_id = r.json()["id"]
    assert (
        api.post(
            "/admin/counsel-codes", json={"code": "SC, X", "office_code": "EDU", "weight": 1.5}, headers=root
        ).status_code
        == 400
    )
    assert (
        api.post(
            "/admin/counsel-codes", json={"code": "SC, X", "office_code": "NOPE"}, headers=root
        ).status_code
        == 400
    )
    # lists: the department admin sees its own codes and the generic ones, never HEALTH's
    codes = [c["code"] for c in api.get("/admin/counsel-codes", headers=admin).json()["items"]]
    assert codes == ["GA, ASSAM", "SC, EDU"]
    assert api.get("/admin/counsel-codes", headers=root).json()["total"] == 3
    assert api.get("/admin/counsel-codes", headers=login(api, "edu_off1")).status_code == 403
    assert (
        api.patch(f"/admin/counsel-codes/{health_id}", json={"notes": "x"}, headers=admin).status_code == 404
    )
    assert (
        api.patch(f"/admin/counsel-codes/{generic_id}", json={"notes": "x"}, headers=admin).status_code == 403
    )
    r = api.patch(
        f"/admin/counsel-codes/{code['id']}",
        json={"office_code": "EDU-DSE", "notes": "schools"},
        headers=admin,
    )
    assert r.status_code == 200 and r.json()["office"]["code"] == "EDU-DSE" and r.json()["notes"] == "schools"
    assert (
        api.patch(f"/admin/counsel-codes/{code['id']}", json={"weight": 0.5}, headers=admin).status_code
        == 403
    )
    r = api.patch(f"/admin/counsel-codes/{code['id']}", json={"weight": None}, headers=root)
    assert r.status_code == 200 and r.json()["weight_override"] is None
    r = api.post(f"/admin/counsel-codes/{code['id']}/deactivate", headers=admin)
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert api.post(f"/admin/counsel-codes/{code['id']}/deactivate", headers=admin).status_code == 400
    assert api.get("/admin/counsel-codes", headers=admin).json()["total"] == 1
    assert api.get("/admin/counsel-codes?include_inactive=true", headers=admin).json()["total"] == 2
    assert (
        api.post(f"/admin/counsel-codes/{code['id']}/reactivate", headers=admin).json()["is_active"] is True
    )
    # keywords, name patterns, watchlist
    r = api.post(
        "/admin/keywords", json={"keyword": "secondary education", "office_code": "EDU"}, headers=admin
    )
    assert (
        r.status_code == 201
        and r.json()["keyword"] == "SECONDARY EDUCATION"
        and r.json()["effective_weight"] == 0.4
    )
    assert (
        api.post(
            "/admin/keywords", json={"keyword": "secondary education", "office_code": "EDU"}, headers=admin
        ).status_code
        == 409
    )
    assert (
        api.post(
            "/admin/keywords", json={"keyword": "hospital", "office_code": "HEALTH"}, headers=admin
        ).status_code
        == 403
    )
    assert api.get("/admin/keywords", headers=admin).json()["total"] == 1
    r = api.post(
        "/admin/name-patterns",
        json={"pattern": "DIRECTOR OF", "kind": "prefix", "office_code": "EDU"},
        headers=admin,
    )
    assert r.status_code == 201 and r.json()["kind"] == "prefix" and r.json()["effective_weight"] == 0.8
    assert (
        api.post(
            "/admin/name-patterns",
            json={"pattern": "(", "kind": "regex", "office_code": "EDU"},
            headers=admin,
        ).status_code
        == 400
    )
    assert (
        api.post(
            "/admin/name-patterns",
            json={"pattern": ".*", "kind": "regex", "office_code": "EDU"},
            headers=admin,
        ).status_code
        == 400
    )
    assert (
        api.post(
            "/admin/name-patterns",
            json={"pattern": "X", "kind": "fuzzy", "office_code": "EDU"},
            headers=admin,
        ).status_code
        == 422
    )
    r = api.post(
        "/admin/watchlist", json={"cnr": "GAHC010000012025", "reason": "minister asked"}, headers=admin
    )
    assert r.status_code == 201, r.text
    assert (
        r.json()["dossier_queued"] is True
        and r.json()["office"]["code"] == "EDU"
        and r.json()["case_ref"] is None
    )
    assert api.post("/admin/watchlist", json={"cnr": "GAHC010000012025"}, headers=admin).status_code == 409
    assert api.post("/admin/watchlist", json={"cnr": "GAHC01000001202X"}, headers=admin).status_code == 400
    assert (
        api.post(
            "/admin/watchlist", json={"cnr": "GAHC010000022025", "office_code": "HEALTH"}, headers=admin
        ).status_code
        == 403
    )
    assert api.get("/admin/watchlist", headers=admin).json()["total"] == 1
    assert api.get("/admin/watchlist", headers=login(api, "health_admin")).json()["total"] == 0
    # the unmapped report and the per-case scores
    r = api.get("/admin/counsel-codes/unmapped", headers=admin)
    assert r.status_code == 200 and r.json() == []
    with world.Session() as s:
        case = make_case(s)
        recommend(s, world, case, "EDU")
        s.commit()
        ref = case.ref_no.replace("/", "-")  # the URL form of a ref_no
    r = api.get(f"/admin/matching/cases/{ref}/scores", headers=root)
    assert r.status_code == 200 and r.json()[0]["office"]["code"] == "EDU" and r.json()[0]["band"] == "high"
    assert api.get(f"/admin/matching/cases/{ref}/scores", headers=admin).status_code == 403
    assert api.get("/admin/matching/cases/GAHC019999992025/scores", headers=root).status_code == 404
    # every rule write left an audit row
    with world.Session() as s:
        actions = set(s.scalars(sa.select(AuditLog.action)).all())
    assert {
        "counsel_code.create",
        "counsel_code.update",
        "counsel_code.deactivate",
        "counsel_code.reactivate",
        "keyword.create",
        "name_pattern.create",
        "watchlist.create",
    } <= actions


# ------------------------------------------------------------------------------------------------ portal-cases 14a/14b


def _listing(s, case, on: date, sr_no: int, *, list_type=ListType.DAILY, court_no: str | None = "3"):
    """A cause-list entry of `case` on `on` (one causelist per date and type)."""
    court = s.scalar(sa.select(Court).where(Court.est_code == "GAHC01"))
    cl = s.scalar(
        sa.select(Causelist).where(
            Causelist.court_id == court.id, Causelist.list_date == on, Causelist.list_type == list_type
        )
    )
    if cl is None:
        cl = Causelist(court_id=court.id, list_date=on, list_type=list_type, source=ListSource.GHC_WEBSITE)
        s.add(cl)
        s.flush()
    s.add(
        CauselistEntry(
            causelist_id=cl.id,
            sr_no=sr_no,
            court_no=court_no,
            case_id=case.id,
            cnr=case.cnr,
            source=EntrySource.PDF_PARSE,
            petitioner_text="X",
            respondent_text="Y",
        )
    )
    s.flush()


def test_recommended_listed_range_filters(api, world):
    with world.Session() as s:
        a, b, c = make_case(s), make_case(s), make_case(s)
        for case in (a, b, c):
            recommend(s, world, case, "EDU")
        _listing(s, a, date(2025, 1, 6), 1)
        _listing(s, b, date(2025, 2, 10), 1)
        s.commit()
        a_id, b_id = str(a.id), str(b.id)
    admin = login(api, "edu_admin")
    assert api.get("/inbox/recommended", headers=admin).json()["total"] == 3
    r = api.get("/inbox/recommended?listed_from=2025-01-01&listed_to=2025-01-31", headers=admin)
    assert r.status_code == 200 and ids(r.json()) == [a_id]
    assert ids(api.get("/inbox/recommended?listed_from=2025-02-01", headers=admin).json()) == [b_id]
    assert sorted(ids(api.get("/inbox/recommended?listed_to=2025-12-31", headers=admin).json())) == sorted(
        [a_id, b_id]
    )
    assert api.get("/inbox/recommended?listed_from=2025-03-01", headers=admin).json()["total"] == 0


def test_recommended_listed_range_reversed_400(api, world):
    admin = login(api, "edu_admin")
    r = api.get("/inbox/recommended?listed_from=2025-02-01&listed_to=2025-01-01", headers=admin)
    assert r.status_code == 400 and "listed_from" in r.json()["detail"]


def test_summary_last_listing_is_latest_entry(api, world):
    with world.Session() as s:
        case = make_case(s)
        recommend(s, world, case, "EDU")
        _listing(s, case, date(2025, 1, 6), 2)
        _listing(s, case, date(2025, 1, 20), 41, court_no="3")
        _listing(s, case, date(2025, 1, 20), 7, list_type=ListType.SUPPLEMENTARY, court_no="5")
        s.commit()
    item = api.get("/inbox/recommended", headers=login(api, "edu_admin")).json()["items"][0]
    assert item["case"]["last_listed_on"] == "2025-01-20"
    assert item["case"]["last_listing"] == {
        "list_date": "2025-01-20",
        "list_type": "supplementary",
        "court_no": "5",
        "sr_no": 7,
    }


def test_summary_last_listing_null_without_entries(api, world):
    with world.Session() as s:
        case = make_case(s)
        recommend(s, world, case, "EDU")
        s.commit()
    item = api.get("/inbox/recommended", headers=login(api, "edu_admin")).json()["items"][0]
    assert item["case"]["last_listing"] is None and item["case"]["last_listed_on"] is None


def test_last_listing_in_search_and_pool_items(api, world):
    with world.Session() as s:
        case = make_case(s)
        _listing(s, case, date(2025, 1, 8), 12, court_no="2")
        s.commit()
        case_id, cnr = str(case.id), case.cnr
    expected = {"list_date": "2025-01-08", "list_type": "daily", "court_no": "2", "sr_no": 12}
    admin = login(api, "edu_admin")
    pool = api.get("/inbox/pool", headers=admin).json()
    item = next(i for i in pool["items"] if str(i["case"]["id"]) == case_id)
    assert item["case"]["last_listing"] == expected
    r = api.get(f"/cases/search?q={cnr}", headers=login(api, "root"))
    assert r.status_code == 200, r.text
    hit = next(i for i in r.json()["items"] if str(i["case"]["id"]) == case_id)
    assert hit["case"]["last_listing"] == expected


# ------------------------------------------------------------------------------------------------ portal-filters

OCT1, OCT2 = date(2026, 10, 1), date(2026, 10, 2)


def _typed(case, type_text, year, *, status=None):
    case.case_type_text, case.reg_year = type_text, year
    if status is not None:
        case.status = status


def test_recommended_filters_case_type_year_status_court_bench_next(api, world):
    with world.Session() as s:
        r1 = make_case(s, next_hearing=date(2026, 10, 20))
        r2 = make_case(s, next_hearing=date(2026, 11, 5), status=CaseStatus.DISPOSED)
        _typed(r1, "WP(C)", 2025)
        _typed(r2, "WA", 2024)
        for case in (r1, r2):
            recommend(s, world, case, "EDU")
        add_listing(s, r1, OCT1, court_no="3", bench=SINGLE_BENCH)
        add_listing(s, r2, OCT2, court_no="5", bench=OTHER_BENCH)
        s.commit()
        r1_id, r2_id = str(r1.id), str(r2.id)
    admin = login(api, "edu_admin")

    def got(query):
        r = api.get(f"/inbox/recommended?{query}", headers=admin)
        assert r.status_code == 200, r.text
        return sorted(ids(r.json()))

    assert got("") == sorted([r1_id, r2_id])
    assert got("case_type=wp(c)") == [r1_id]
    assert got("year=2024") == [r2_id]
    assert got("case_status=disposed") == [r2_id]
    assert got("court_no=3") == [r1_id]
    assert got("bench=phukan") == [r2_id]
    assert got("next_from=2026-10-01&next_to=2026-10-31") == [r1_id]
    assert got("listed_from=2026-10-01&listed_to=2026-10-01&court_no=5") == []
    every = "case_type=WA&year=2024&case_status=disposed&court_no=5&bench=PHUKAN&next_from=2026-11-01"
    assert got(every) == [r2_id]
    for bad in ("year=99", "case_status=open", "bench=ab", "next_from=2026-11-02&next_to=2026-11-01", "q=ab"):
        r = api.get(f"/inbox/recommended?{bad}", headers=admin)
        assert r.status_code == 400, bad


def test_claimed_filters_listed_and_next(api, world):
    with world.Session() as s:
        a = make_case(s, next_hearing=date(2026, 10, 20))
        b = make_case(s)
        add_listing(s, a, OCT1)
        add_listing(s, b, OCT2)
        s.commit()
        a_id, b_id = str(a.id), str(b.id)
    admin = login(api, "edu_admin")
    for cid in (a_id, b_id):
        assert api.post(f"/cases/{cid}/claim", json={}, headers=admin).status_code == 201
    assert sorted(ids(api.get("/inbox/claimed", headers=admin).json())) == sorted([a_id, b_id])
    r = api.get("/inbox/claimed?listed_from=2026-10-01&listed_to=2026-10-01", headers=admin)
    assert r.status_code == 200 and ids(r.json()) == [a_id] and r.json()["total"] == 1
    assert ids(api.get("/inbox/claimed?listed_from=2026-10-02", headers=admin).json()) == [b_id]
    assert ids(api.get("/inbox/claimed?next_to=2026-10-31", headers=admin).json()) == [a_id]
    r = api.get("/inbox/claimed?case_state=disposed&listed_from=2026-10-01", headers=admin)
    assert r.json()["total"] == 0


def test_pool_case_type_uses_master_names(api, world):
    from aslms.domain.courts import CaseType

    with world.Session() as s:
        court = s.scalar(sa.select(Court).where(Court.est_code == "GAHC01"))
        ct = CaseType(
            court_id=court.id, case_type_code=9201, type_name="WP(C)", short_name="WP(C)", aliases=["WPC"]
        )
        s.add(ct)
        s.flush()
        typed = make_case(s)
        typed.case_type_id = ct.id  # no type text: the old exact-text match missed it
        texted = make_case(s)
        texted.case_type_text = "WA"
        s.commit()
        typed_id, texted_id = str(typed.id), str(texted.id)
    admin = login(api, "edu_admin")
    assert ids(api.get("/inbox/pool?case_type=WPC", headers=admin).json()) == [typed_id]
    assert ids(api.get("/inbox/pool?case_type=wp(c)", headers=admin).json()) == [typed_id]
    assert ids(api.get("/inbox/pool?case_type=wa", headers=admin).json()) == [texted_id]
    assert api.get("/inbox/pool?case_type=%20", headers=admin).status_code == 400


def test_pool_scored_for_with_min_score_same_row(api, world):
    with world.Session() as s:
        c1, c2 = make_case(s), make_case(s)
        make_case(s)
        for case, code, score in ((c1, "EDU", 0.4), (c1, "HEALTH", 0.9), (c2, "EDU", 0.7)):
            s.add(
                CaseOfficeScore(
                    case_id=case.id,
                    office_id=world.offices[code].id,
                    score=score,
                    signals=[],
                    engine_version="1.1",
                )
            )
        s.commit()
        c1_id, c2_id = str(c1.id), str(c2.id)
    admin = login(api, "edu_admin")

    def got(query):
        r = api.get(f"/inbox/pool?{query}", headers=admin)
        assert r.status_code == 200, r.text
        return sorted(ids(r.json()))

    assert got("scored_for=edu") == sorted([c1_id, c2_id])
    assert got("scored_for=EDU&min_score=0.5") == [c2_id]  # c1's 0.9 is HEALTH's row
    assert got("min_score=0.5") == sorted([c1_id, c2_id])
    assert got("scored_for=HEALTH") == [c1_id]
    r = api.get("/inbox/pool?scored_for=EDU-DSE", headers=admin)
    assert r.status_code == 400 and "is not a department" in r.json()["detail"]


def test_pool_status_alias_and_conflict_400(api, world):
    with world.Session() as s:
        make_case(s)
        d = make_case(s, status=CaseStatus.DISPOSED)
        s.commit()
        d_id = str(d.id)
    admin = login(api, "edu_admin")
    assert ids(api.get("/inbox/pool?status=disposed", headers=admin).json()) == [d_id]
    assert ids(api.get("/inbox/pool?case_status=disposed", headers=admin).json()) == [d_id]
    assert ids(api.get("/inbox/pool?status=disposed&case_status=disposed", headers=admin).json()) == [d_id]
    r = api.get("/inbox/pool?status=disposed&case_status=pending", headers=admin)
    assert r.status_code == 400 and r.json()["detail"] == "status and case_status differ"


def test_transfers_case_filters_and_other_office(api, world):
    with world.Session() as s:
        a, b = make_case(s), make_case(s)
        _typed(a, "WP(C)", 2025)
        _typed(b, "WA", 2024)
        s.commit()
        a_id, b_id = str(a.id), str(b.id)
    admin = login(api, "edu_admin")
    health = login(api, "health_admin")
    for cid in (a_id, b_id):
        assert api.post(f"/cases/{cid}/claim", json={}, headers=admin).status_code == 201
        body = {"to_office_code": "HEALTH", "reason": "x"}
        r = api.post(f"/cases/{cid}/transfers", json=body, headers=admin)
        assert r.status_code == 201, r.text

    def got(headers, query):
        r = api.get(f"/inbox/transfers?{query}", headers=headers)
        assert r.status_code == 200, r.text
        return sorted(ids(r.json()))

    both = sorted([a_id, b_id])
    assert got(admin, "direction=out&other_office=HEALTH") == both
    assert got(admin, "direction=in&other_office=HEALTH") == []
    assert got(admin, "other_office=health") == both
    assert got(health, "direction=in&other_office=EDU") == both
    assert got(health, "direction=out&other_office=EDU") == []
    assert got(admin, "direction=out&year=2025") == [a_id]
    assert got(health, "direction=in&case_type=WA") == [b_id]
    assert got(admin, "status=requested&case_status=pending") == both
    r = api.get("/inbox/transfers?other_office=EDU-DSE", headers=admin)
    assert r.status_code == 400 and "is not a department" in r.json()["detail"]


def test_inbox_words_match_advocate_and_case_number(api, world):
    with world.Session() as s:
        a = make_case(s, case_no="WP(C)/4326/2025", pet="ASSAM TEA CORPORATION")
        b = make_case(s, pet="RAM KUMAR")
        entry = add_listing(s, b, OCT1)
        entry.res_advocate_text = "SC, ELEM. EDU"
        entry.pet_advocate_text = "MR. B KATHAR"
        s.flush()
        refresh_search_vector(s, [a.id, b.id])
        for case in (a, b):
            recommend(s, world, case, "EDU")
        s.commit()
        a_id, b_id = str(a.id), str(b.id)
    admin = login(api, "edu_admin")
    for tab in ("recommended", "pool"):
        assert ids(api.get(f"/inbox/{tab}", params={"q": "WP(C) 4326/2025"}, headers=admin).json()) == [a_id]
        assert ids(api.get(f"/inbox/{tab}", params={"q": "kathar"}, headers=admin).json()) == [b_id]
        assert ids(api.get(f"/inbox/{tab}", params={"q": "elem edu"}, headers=admin).json()) == [b_id]
        assert ids(api.get(f"/inbox/{tab}", params={"q": "Assa"}, headers=admin).json()) == [a_id]


def test_filters_never_widen_claimed_scope(api, world):
    with world.Session() as s:
        a, b = make_case(s), make_case(s)
        add_listing(s, a, OCT1)
        add_listing(s, b, OCT1)
        s.commit()
        a_id, b_id = str(a.id), str(b.id)
        off1 = str(world.users["edu_off1"].id)
    admin = login(api, "edu_admin")
    assert api.post(f"/cases/{a_id}/claim", json={"officer_user_id": off1}, headers=admin).status_code == 201
    assert api.post(f"/cases/{b_id}/claim", json={}, headers=admin).status_code == 201
    officer = login(api, "edu_off1")
    plain = set(ids(api.get("/inbox/claimed", headers=officer).json()))
    assert plain == {a_id}
    for query in ("listed_from=2026-10-01", "court_no=3", "bench=SAIKIA", "case_status=pending"):
        filtered = set(ids(api.get(f"/inbox/claimed?{query}", headers=officer).json()))
        assert filtered <= plain and b_id not in filtered, query
    # the pool never holds the claimed cases, whatever the filter
    assert api.get("/inbox/pool?listed_from=2026-10-01", headers=admin).json()["total"] == 0


def test_dashboard_counts_unchanged_by_filters_module(api, world):
    with world.Session() as s:
        r1, r2 = make_case(s), make_case(s)
        recommend(s, world, r1, "EDU", score=0.95, band=ScoreBand.HIGH)
        recommend(s, world, r2, "EDU", score=0.6, band=ScoreBand.MEDIUM)
        c = make_case(s, next_hearing=today_ist() + timedelta(days=2))
        add_listing(s, r1, OCT1)
        s.commit()
        c_id = str(c.id)
    admin = login(api, "edu_admin")
    assert api.post(f"/cases/{c_id}/claim", json={}, headers=admin).status_code == 201
    counts = api.get("/inbox/counts", headers=admin).json()["departments"][0]
    assert counts["recommended_high"] == 1 and counts["recommended_medium"] == 1
    assert counts["claimed_active"] == 1 and counts["claimed_disposed"] == 0
    # a filtered list changes its own total, never the counts (the badges say what is waiting)
    assert api.get("/inbox/recommended?listed_from=2026-10-01", headers=admin).json()["total"] == 1
    assert api.get("/inbox/claimed?year=1999", headers=admin).json()["total"] == 0
    assert api.get("/inbox/counts?year=1999", headers=admin).json()["departments"][0] == counts
    assert api.get("/dashboard", headers=admin).status_code == 200


# ------------------------------------------------------------------------------------------------ portal-ui-redesign


def test_claimed_filters_unallotted_stage_holder_action(api, world):
    """Design portal-ui-redesign, A3: the new `/inbox/claimed` filters narrow, and items carry stage and custody."""
    from aslms.domain.workflow import Custody, PendingAction
    from aslms.services import stages
    from aslms.services.workflow_common import today_ist
    from tests.db import workflow_support as w

    with world.Session() as s:
        a = w.claimed_case(s, world, officer="edu_off1")
        b = w.claimed_case(s, world, officer=None)
        c = w.claimed_case(s, world, officer="edu_off2")
        w.send(s, world, "edu_off2", c, "health_off")  # the file leaves the department
        actor, admin = world.actor(s, "edu_admin")
        stages.set_stage(s, actor, admin, a, stage="affidavit_filed")
        held_a = s.get(Custody, a.id)
        held_a.due_date, held_a.pending_action = today_ist() - timedelta(days=2), PendingAction.EXAMINE
        s.get(Custody, c.id).due_date = today_ist() + timedelta(days=5)
        s.commit()
        a_id, b_id, c_id = str(a.id), str(b.id), str(c.id)
        off1 = str(world.users["edu_off1"].id)
    admin = login(api, "edu_admin")

    def got(query):
        r = api.get(f"/inbox/claimed?{query}", headers=admin)
        assert r.status_code == 200, r.text
        return sorted(ids(r.json()))

    assert got("") == sorted([a_id, b_id, c_id])
    assert got("unallotted=true") == [b_id]
    assert got("stage=affidavit_filed") == [a_id]
    assert got("stage=none") == sorted([b_id, c_id])
    assert got("holder=elsewhere") == [c_id]
    assert got("holder=department") == sorted([a_id, b_id])
    assert got("action=overdue") == [a_id]
    assert got("action=due_week") == [c_id]
    assert got("unallotted=true&stage=none") == [b_id]
    for bad in (
        f"unallotted=true&officer_user_id={off1}",
        "stage=nonsense",
        "holder=somewhere",
        "action=later",
    ):
        assert api.get(f"/inbox/claimed?{bad}", headers=admin).status_code == 400, bad
    items = {str(i["case"]["id"]): i for i in api.get("/inbox/claimed", headers=admin).json()["items"]}
    assert items[a_id]["stage"]["stage"] == "affidavit_filed" and items[a_id]["stage"]["phase"]
    assert items[a_id]["custody"]["holder_user"]["full_name"] == "Edu Off1"
    assert items[a_id]["custody"]["overdue"] is True and items[a_id]["custody"]["with_me"] is False
    assert items[c_id]["custody"]["holder_office"]["code"] == "HEALTH"
    assert items[b_id]["stage"] is None
    # the officer reads only their own allotment, with the file "with me"
    mine_items = api.get("/inbox/claimed", headers=login(api, "edu_off1")).json()["items"]
    assert [str(i["case"]["id"]) for i in mine_items] == [a_id]
    assert mine_items[0]["custody"]["with_me"] is True


def test_counts_whole_department_flag(api, world):
    """Design portal-ui-redesign, A4: `whole_department` per department block."""

    def flag(key, query=""):
        r = api.get(f"/inbox/counts{query}", headers=login(api, key))
        assert r.status_code == 200, r.text
        return [d["whole_department"] for d in r.json()["departments"]]

    assert flag("edu_admin") == [True]
    assert flag("edu_head") == [True]
    assert flag("edu_off1") == [False]
    assert flag("dse_user") == [False]
    assert flag("oversight", "?office=EDU") == [True]
    assert flag("oversight", "?office=HEALTH") == [True]
