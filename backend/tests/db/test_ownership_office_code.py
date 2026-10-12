"""Dismiss and allot act for the department on screen (design `portal-cases`, deviation 10): a login with
memberships in EDU (primary) and HEALTH, both holding `cases.dismiss` and `cases.allot`, names HEALTH with
`office_code` and HEALTH's recommendation or ownership row changes, not EDU's; without `office_code` the primary
membership acts as before; `office_code` must name one of the caller's own departments (the super admin gains
nothing here)."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from aslms.api.main import create_app
from aslms.core.config import Settings
from aslms.domain.events import AuditLog
from aslms.domain.org import PermissionEffect
from aslms.domain.ownership import CaseOwnership, OwnershipStatus, Recommendation, RecommendationStatus
from aslms.domain.reference import Permission, Role
from aslms.services import access
from aslms.services import ownership as own
from tests.db.auth_support import bearer
from tests.db.test_ownership import recommend
from tests.db.world import PW, USERS, add_membership, make_case


@pytest.fixture()
def dual(world):
    """The EDU admin also works in HEALTH, where the HEALTH admin grants dismiss and allot."""
    with world.Session() as s:
        add_membership(
            s, world.user(s, "edu_admin"), world.office(s, "HEALTH"), Role.DEPT_OFFICER, "Under Secretary"
        )
        s.flush()
        h_actor, h_admin = world.actor(s, "health_admin")
        health_m = world.membership(s, "edu_admin", "HEALTH")
        for perm in (Permission.CASES_DISMISS, Permission.CASES_ALLOT):
            access.set_override(s, h_actor, h_admin, health_m, perm, PermissionEffect.GRANT)
        s.commit()
    return world


def _row(s, world, case, code) -> CaseOwnership:
    return s.scalar(
        sa.select(CaseOwnership).where(
            CaseOwnership.case_id == case.id,
            CaseOwnership.office_id == world.offices[code].id,
            CaseOwnership.status == OwnershipStatus.ACTIVE,
        )
    )


def _held_by_both(s, w):
    """A case EDU holds as primary and HEALTH as watcher."""
    case = make_case(s)
    h_actor, h_admin = w.actor(s, "health_admin")
    actor, person = w.actor(s, "edu_admin")
    own.claim(s, actor, person, case, office_code="EDU")
    recommend(s, w, case, "HEALTH")
    own.claim(s, h_actor, h_admin, case)
    return case


def test_dismiss_acts_for_the_named_department(dual):
    w = dual
    with w.Session() as s:
        actor, person = w.actor(s, "edu_admin")
        case = make_case(s)
        edu_rec = recommend(s, w, case, "EDU")
        health_rec = recommend(s, w, case, "HEALTH")
        own.dismiss(s, actor, person, case, reason="not a health matter", office_code="HEALTH")
        assert health_rec.status == RecommendationStatus.DISMISSED
        assert edu_rec.status == RecommendationStatus.RECOMMENDED
        audit = s.scalar(
            sa.select(AuditLog).where(
                AuditLog.case_id == case.id, AuditLog.action == "recommendation.dismiss"
            )
        )
        assert audit.after["office_code"] == "HEALTH"
        assert audit.actor_office_code == "HEALTH"
        # without office_code the primary membership (EDU) acts, as before
        own.dismiss(s, actor, person, case)
        assert edu_rec.status == RecommendationStatus.DISMISSED


def test_dismiss_office_code_without_a_recommendation_there(dual):
    w = dual
    with w.Session() as s:
        actor, person = w.actor(s, "edu_admin")
        case = make_case(s)
        edu_rec = recommend(s, w, case, "EDU")
        with pytest.raises(own.NotVisible):
            own.dismiss(s, actor, person, case, office_code="HEALTH")
        assert edu_rec.status == RecommendationStatus.RECOMMENDED


def test_allot_acts_for_the_named_department(dual):
    w = dual
    with w.Session() as s:
        actor, person = w.actor(s, "edu_admin")
        case = _held_by_both(s, w)
        health_off = w.user(s, "health_off")
        # without office_code EDU acts, and a HEALTH officer is not eligible there
        with pytest.raises(own.OwnershipError, match="not an eligible user of EDU"):
            own.allot(s, actor, person, case, officer_user_id=health_off.id)
        row = own.allot(s, actor, person, case, officer_user_id=health_off.id, office_code="HEALTH")
        assert row.office_id == w.offices["HEALTH"].id and row.officer_user_id == health_off.id
        assert _row(s, w, case, "EDU").officer_user_id is None


def test_office_code_names_one_of_the_callers_departments(dual):
    w = dual
    with w.Session() as s:
        case = make_case(s)
        recommend(s, w, case, "EDU")
        h_rec = recommend(s, w, case, "HEALTH")
        actor, admin = w.actor(s, "health_admin")
        with pytest.raises(own.OwnershipError, match="no membership in EDU"):
            own.dismiss(s, actor, admin, case, office_code="EDU")
        with pytest.raises(own.OwnershipError, match="not an active department"):
            own.dismiss(s, actor, admin, case, office_code="NOPE")
        # the super admin, who may claim for any department, does not dismiss or allot for one
        r_actor, root = w.actor(s, "root")
        with pytest.raises(own.OwnershipError, match="no membership in HEALTH"):
            own.dismiss(s, r_actor, root, case, office_code="HEALTH")
        assert h_rec.status == RecommendationStatus.RECOMMENDED


# ------------------------------------------------------------------------------------------------ API


@pytest.fixture()
def api(dual):
    settings = Settings(
        _env_file=None,
        aslms_jwt_secret="test-secret-of-at-least-thirty-two-characters",
        aslms_access_token_minutes=5,
    )
    app = create_app(settings, dual.Session)
    with TestClient(app) as client:
        yield client


def test_api_dismiss_and_allot_take_office_code(dual, api):
    w = dual
    with w.Session() as s:
        rec_case = make_case(s)
        edu_rec = recommend(s, w, rec_case, "EDU")
        health_rec = recommend(s, w, rec_case, "HEALTH")
        held = _held_by_both(s, w)
        rec_id, held_id = str(rec_case.id), str(held.id)
        edu_rec_id, health_rec_id = edu_rec.id, health_rec.id
        health_off = str(w.users["health_off"].id)
        s.commit()
    h = bearer(api, USERS["edu_admin"][0], PW)
    r = api.post(f"/cases/{rec_id}/dismiss", json={"office_code": "HEALTH"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["office_code"] == "HEALTH" and r.json()["status"] == "dismissed"
    r = api.post(f"/cases/{held_id}/allot", json={"officer_user_id": health_off}, headers=h)
    assert r.status_code == 400
    r = api.post(
        f"/cases/{held_id}/allot", json={"office_code": "HEALTH", "officer_user_id": health_off}, headers=h
    )
    assert r.status_code == 200, r.text
    assert r.json()["office_code"] == "HEALTH"
    r = api.post(f"/cases/{rec_id}/dismiss", json={"office_code": "CENTRAL"}, headers=h)
    assert r.status_code == 400
    with w.Session() as s:
        assert s.get(Recommendation, edu_rec_id).status == RecommendationStatus.RECOMMENDED
        assert s.get(Recommendation, health_rec_id).status == RecommendationStatus.DISMISSED
