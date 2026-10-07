"""Negative paths and audit boundaries for recommend-and-claim: the engine writes no audit rows, a merged
case's engine recommendations expire, refused actions leave no audit row or event, a disabled user is 401 on
the inbox and ownership endpoints, and unknown references are 404."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from aslms.api.main import create_app
from aslms.core.config import Settings
from aslms.domain.events import AuditLog, Event
from aslms.domain.ownership import (
    CounselCode,
    Recommendation,
    RecommendationOrigin,
    RecommendationStatus,
    ScoreBand,
)
from aslms.services import access, matching
from aslms.services import ownership as own
from tests.db.auth_support import bearer
from tests.db.world import PW, USERS, make_case


@pytest.fixture()
def api(world):
    settings = Settings(
        _env_file=None,
        aslms_jwt_secret="test-secret-of-at-least-thirty-two-characters",
        aslms_access_token_minutes=5,
    )
    with TestClient(create_app(settings, world.Session)) as client:
        yield client


def login(api, key):
    return bearer(api, USERS[key][0], PW)


def counts(s, case_id):
    a = s.scalar(sa.select(sa.func.count()).select_from(AuditLog).where(AuditLog.case_id == case_id))
    e = s.scalar(sa.select(sa.func.count()).select_from(Event).where(Event.case_id == case_id))
    return a, e


def rec(s, world, case, code):
    r = Recommendation(
        case_id=case.id,
        office_id=world.offices[code].id,
        score=0.95,
        band=ScoreBand.HIGH,
        origin=RecommendationOrigin.CAUSE_LIST,
        actor_name="matching",
    )
    s.add(r)
    s.flush()
    return r


def test_engine_writes_no_audit_rows_and_merged_case_expires(world):
    with world.Session() as s:
        s.add(CounselCode(code="SC, EDU", office_id=world.offices["EDU"].id))
        case = make_case(s)
        other = make_case(s)
        from aslms.domain.cases import AdvocateSide, CaseAdvocate

        s.add(
            CaseAdvocate(
                case_id=case.id,
                side=AdvocateSide.RESPONDENT,
                name_as_listed="SC, EDU",
                counsel_code="SC, EDU",
            )
        )
        s.flush()
        before = s.scalar(sa.select(sa.func.count()).select_from(AuditLog))
        matching.score_cases(s, [case.id], origin=RecommendationOrigin.RESCORE)
        s.commit()
        assert s.scalar(sa.select(sa.func.count()).select_from(AuditLog)) == before
        r = s.scalar(sa.select(Recommendation).where(Recommendation.case_id == case.id))
        assert r.status == RecommendationStatus.RECOMMENDED
        case.merged_into_case_id = other.id
        s.flush()
        matching.score_cases(s, [case.id], origin=RecommendationOrigin.RESCORE)
        s.commit()
        s.refresh(r)
        assert r.status == RecommendationStatus.EXPIRED and r.acted_at is not None


def test_refused_actions_leave_no_audit_or_event(world):
    with world.Session() as s:
        case = make_case(s)
        n0 = counts(s, case.id)
        # no recommendation, not the pool-owner: dismiss, suggest-less transfer, allot, take-over, unwatch
        actor, admin = world.actor(s, "edu_admin")
        with pytest.raises(own.OwnershipError):
            own.dismiss(s, actor, admin, case)
        with pytest.raises(own.OwnershipError):
            own.stop_watching(s, actor, admin, case, reason="x")
        with pytest.raises(own.OwnershipError):
            own.request_transfer(s, actor, admin, case, to_office_code="HEALTH", reason="x")
        with pytest.raises(own.OwnershipError):
            own.allot(s, actor, admin, case, unit_code="EDU-DSE")
        o_actor, officer = world.actor(s, "edu_off1")
        with pytest.raises(access.Forbidden):
            own.claim(s, o_actor, officer, case)
        a_actor, auditor = world.actor(s, "edu_auditor")
        with pytest.raises(access.Forbidden):
            own.claim(s, a_actor, auditor, case)
        assert counts(s, case.id) == n0

        # a claimed case: a third department cannot decide a transfer, nor request one
        own.claim(s, actor, admin, case)
        trf = own.request_transfer(s, actor, admin, case, to_office_code="CENTRAL", reason="r")
        n1 = counts(s, case.id)
        h_actor, h_admin = world.actor(s, "health_admin")
        with pytest.raises(own.OwnershipError):
            own.decide_transfer(s, h_actor, h_admin, trf, accept=True)
        with pytest.raises(own.OwnershipError):
            own.request_transfer(s, h_actor, h_admin, case, to_office_code="EDU", reason="r")
        assert counts(s, case.id) == n1


def test_disabled_user_is_401_on_inbox_and_ownership(api, world):
    with world.Session() as s:
        case = make_case(s)
        rec(s, world, case, "EDU")
        s.commit()
        ref = case.ref_no.replace("/", "-")
    headers = login(api, "edu_admin")
    assert api.get("/inbox/recommended", headers=headers).status_code == 200
    with world.Session() as s:
        u = s.get(type(world.users["edu_admin"]), world.users["edu_admin"].id)
        u.is_active = False
        s.commit()
    assert api.get("/inbox/recommended", headers=headers).status_code == 401
    assert api.get("/inbox/counts", headers=headers).status_code == 401
    assert api.post(f"/cases/{ref}/claim", json={}, headers=headers).status_code == 401
    with world.Session() as s:
        assert (
            s.scalar(sa.select(sa.func.count()).select_from(AuditLog).where(AuditLog.case_id == case.id)) == 0
        )


def test_unknown_references_and_missing_functions_over_the_api(api, world):
    admin = login(api, "edu_admin")
    for path, body in [
        ("claim", {}),
        ("dismiss", {}),
        ("allot", {}),
        ("take-over", {}),
        ("stop-watching", {"reason": "x"}),
        ("transfers", {"to_office_code": "HEALTH", "reason": "x"}),
    ]:
        r = api.post(f"/cases/ASHC019999992025/{path}", json=body, headers=admin)
        assert r.status_code == 404, (path, r.status_code)
    assert api.post("/transfers/does-not-exist/accept", json={}, headers=admin).status_code == 404
    assert api.get("/cases/ASHC019999992025/ownership", headers=admin).status_code == 404
    with world.Session() as s:
        case = make_case(s)
        s.commit()
        ref = case.ref_no.replace("/", "-")
    aud = login(api, "edu_auditor")
    assert api.post(f"/cases/{ref}/claim", json={}, headers=aud).status_code == 403
    assert (
        api.post(
            f"/cases/{ref}/transfers", json={"to_office_code": "HEALTH", "reason": "x"}, headers=aud
        ).status_code
        == 403
    )
    assert api.put("/admin/scoring-settings", json={}, headers=aud).status_code in (403, 422)
