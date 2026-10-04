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
    r = api.post("/auth/login", json={"email": USERS[key][0], "password": PW})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


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
    assert body["items"][0]["case"]["next_hearing_date"] == "2026-10-20"
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
    counts = api.get("/inbox/counts", headers=admin).json()
    assert counts["claimed_active"] == 2 and counts["claimed_disposed"] == 1
    assert counts["recommended_high"] == 0 and counts["transfers_in_open"] == 0
    counts = api.get("/inbox/counts", headers=login(api, "edu_off1")).json()
    assert counts["claimed_active"] == 1 and counts["recommended_high"] is None
    assert counts["pool_with_hearing_7d"] is None and counts["transfers_in_open"] is None


# ------------------------------------------------------------------------------------------------ pool


def test_pool_excludes_owned_and_filters(api, world):
    with world.Session() as s:
        q1 = make_case(s, pet="RAM KUMAR", next_hearing=date.today() + timedelta(days=3))
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
    assert api.get("/inbox/counts", headers=health).json()["transfers_in_open"] == 1
    assert api.get("/inbox/transfers", headers=login(api, "health_off")).status_code == 403
    r = api.post(f"/transfers/{trf['id']}/accept", json={"note": "ok"}, headers=health)
    assert r.status_code == 200 and r.json()["status"] == "accepted" and r.json()["decision_note"] == "ok"
    assert api.get("/inbox/counts", headers=health).json()["transfers_in_open"] == 0
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
    assert api.get("/inbox/counts", headers=admin).json()["pool_with_hearing_7d"] == 1


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
    assert api.post("/cases/ASLMS-GOA-CASE-2099-999999/claim", json={}, headers=admin).status_code == 404
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
                sa.select(AuditLog.action).where(AuditLog.case_id == t1.id).order_by(AuditLog.created_at)
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
    assert r.status_code == 200 and r.json()["version"] == 1 and r.json()["engine_version"] == "1.1"
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
    assert r.json()["applies_within_minutes"] == 15 and r.json()["engine_version"] == "1.2"
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
