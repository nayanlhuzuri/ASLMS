"""Dismiss and allot act for the department on screen (design `portal-cases`, deviation 10): a login with
memberships in EDU (primary) and HEALTH, both holding `cases.dismiss` and `cases.allot`, names HEALTH with
`office_code` and HEALTH's recommendation or ownership row changes, not EDU's; without `office_code` the primary
membership acts as before; `office_code` must name one of the caller's own departments (the super admin gains
nothing here). The follow-ups (design `portal-cases-followups`) extend the same rule to suggest, take over and
stop watching, and a transfer request acts for the primary owner's department."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from aslms.api.main import create_app
from aslms.core.config import Settings
from aslms.domain.events import AuditLog
from aslms.domain.org import Office, PermissionEffect
from aslms.domain.ownership import CaseOwnership, OwnershipStatus, Recommendation, RecommendationStatus
from aslms.domain.reference import OfficeKind, Permission, Role
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


# ------------------------------------------------------------------------------------------------ portal-cases-followups
# Design `portal-cases-followups`, decisions 2 and 3: suggest names the department it comes from, take over and
# stop watching name the department that acts, and a transfer request acts for the primary owner's department.


def _grant(s, w, perms, *, key="edu_admin", code="HEALTH", by="health_admin", effect=PermissionEffect.GRANT):
    a, admin = w.actor(s, by)
    m = w.membership(s, key, code)
    for perm in perms:
        access.set_override(s, a, admin, m, perm, effect)
    s.flush()


def _audit(s, case, action) -> AuditLog:
    return s.scalar(
        sa.select(AuditLog)
        .where(AuditLog.case_id == case.id, AuditLog.action == action)
        .order_by(AuditLog.id.desc())
        .limit(1)
    )


def test_suggest_from_named_department(dual):
    w = dual
    with w.Session() as s:
        _grant(s, w, [Permission.CASES_SUGGEST_ELSEWHERE])
        actor, person = w.actor(s, "edu_admin")
        case = make_case(s)
        edu_rec = recommend(s, w, case, "EDU")
        health_rec = recommend(s, w, case, "HEALTH")
        result = own.suggest(
            s, actor, person, case, office_code="EDU", reason="an education matter", from_office_code="HEALTH"
        )
        assert result.own is health_rec and result.target_already_recommended is True
        assert health_rec.status == RecommendationStatus.SUGGESTED_ELSEWHERE
        assert edu_rec.status == RecommendationStatus.RECOMMENDED
        audit = _audit(s, case, "recommendation.suggest")
        assert audit.after["from_office_code"] == "HEALTH" and audit.after["to_office_code"] == "EDU"
        assert audit.actor_office_code == "HEALTH"


def test_suggest_from_must_be_own_related_department(dual):
    w = dual
    with w.Session() as s:
        case = make_case(s)
        recommend(s, w, case, "EDU")
        h_rec = recommend(s, w, case, "HEALTH")
        actor, person = w.actor(s, "edu_admin")
        h_actor, h_admin = w.actor(s, "health_admin")
        # 400: not one of the caller's departments (the super admin gains nothing either)
        with pytest.raises(own.OwnershipError, match="no membership in EDU"):
            own.suggest(s, h_actor, h_admin, case, office_code="EDU", reason="r", from_office_code="EDU")
        r_actor, root = w.actor(s, "root")
        with pytest.raises(own.OwnershipError, match="no membership in HEALTH"):
            own.suggest(s, r_actor, root, case, office_code="EDU", reason="r", from_office_code="HEALTH")
        # 403: the HEALTH membership lacks cases.suggest_elsewhere
        with pytest.raises(access.Forbidden):
            own.suggest(s, actor, person, case, office_code="EDU", reason="r", from_office_code="HEALTH")
        # 404: a named department with no recommendation or row for the case
        _grant(s, w, [Permission.CASES_SUGGEST_ELSEWHERE])
        other = make_case(s)
        recommend(s, w, other, "EDU")
        with pytest.raises(own.NotVisible, match="no recommendation or ownership of HEALTH"):
            own.suggest(s, actor, person, other, office_code="EDU", reason="r", from_office_code="HEALTH")
        # the named department cannot suggest itself
        with pytest.raises(own.OwnershipError, match="other than your own"):
            own.suggest(s, actor, person, case, office_code="HEALTH", reason="r", from_office_code="HEALTH")
        assert h_rec.status == RecommendationStatus.RECOMMENDED


def _held_and_allotted(s, w):
    """EDU primary allotted to EDU officer 1, HEALTH watcher allotted to the HEALTH officer."""
    case = make_case(s)
    actor, person = w.actor(s, "edu_admin")
    own.claim(s, actor, person, case, office_code="EDU", officer_user_id=w.users["edu_off1"].id)
    recommend(s, w, case, "HEALTH")
    h_actor, h_admin = w.actor(s, "health_admin")
    own.claim(s, h_actor, h_admin, case)
    own.allot(s, h_actor, h_admin, case, officer_user_id=w.users["health_off"].id)
    return case


def test_take_over_acts_for_named_department(dual):
    w = dual
    with w.Session() as s:
        case = _held_and_allotted(s, w)
        actor, person = w.actor(s, "edu_admin")
        result = own.take_over(
            s,
            actor,
            person,
            case,
            office_code="HEALTH",
            expected_officer_user_id=w.users["health_off"].id,
        )
        assert result.ownership.office_id == w.offices["HEALTH"].id
        assert result.ownership.officer_user_id == person.id
        assert result.previous.id == w.users["health_off"].id
        assert _row(s, w, case, "EDU").officer_user_id == w.users["edu_off1"].id
        audit = _audit(s, case, "ownership.take_over")
        assert audit.after["office_code"] == "HEALTH" and audit.actor_office_code == "HEALTH"


def test_take_over_office_code_refusals(dual):
    w = dual
    with w.Session() as s:
        case = _held_and_allotted(s, w)
        actor, person = w.actor(s, "edu_admin")
        h_actor, h_admin = w.actor(s, "health_admin")
        with pytest.raises(own.OwnershipError, match="no membership in EDU"):
            own.take_over(s, h_actor, h_admin, case, office_code="EDU")
        with pytest.raises(own.OwnershipError, match="not an active department"):
            own.take_over(s, actor, person, case, office_code="NOPE")
        # the stale check still runs for the named department
        with pytest.raises(own.OwnershipConflict) as exc:
            own.take_over(
                s, actor, person, case, office_code="HEALTH", expected_officer_user_id=w.users["edu_off1"].id
            )
        assert exc.value.code == "stale"
        # 404: a named department without a row for the case
        pool = make_case(s)
        with pytest.raises(own.NotVisible):
            own.take_over(s, actor, person, pool, office_code="HEALTH")
        # 403: the HEALTH membership's take-over denied
        _grant(s, w, [Permission.CASES_TAKE_OVER], effect=PermissionEffect.DENY)
        with pytest.raises(access.Forbidden):
            own.take_over(s, actor, person, case, office_code="HEALTH")
        assert _row(s, w, case, "HEALTH").officer_user_id == w.users["health_off"].id


def _third_department(s, w):
    """A department REV under GOA, so one login can watch a case from EDU and HEALTH."""
    goa = w.office(s, "GOA")
    rev = Office(
        code="REV", name="Revenue", kind=OfficeKind.DEPARTMENT, parent_id=goa.id, path=f"{goa.path}/REV"
    )
    s.add(rev)
    s.flush()
    w.offices["REV"] = rev
    return rev


def _watched_from_both(s, w):
    """REV primary (claimed by the super admin for it); EDU and HEALTH watchers; the central operator works in
    EDU and HEALTH as an officer with cases.release in both, its primary membership in neither."""
    _third_department(s, w)
    op = w.user(s, "central_op")
    add_membership(s, op, w.office(s, "EDU"), Role.DEPT_OFFICER)
    add_membership(s, op, w.office(s, "HEALTH"), Role.DEPT_OFFICER)
    s.flush()
    _grant(s, w, [Permission.CASES_RELEASE], key="central_op", code="EDU", by="edu_admin")
    _grant(s, w, [Permission.CASES_RELEASE], key="central_op", code="HEALTH", by="health_admin")
    case = make_case(s)
    r_actor, root = w.actor(s, "root")
    own.claim(s, r_actor, root, case, office_code="REV")
    for code, key in (("EDU", "edu_admin"), ("HEALTH", "health_admin")):
        recommend(s, w, case, code)
        a, u = w.actor(s, key)
        own.claim(s, a, u, case, office_code=code)
    return case


def test_stop_watching_two_watcher_rows(dual):
    w = dual
    with w.Session() as s:
        case = _watched_from_both(s, w)
        actor, op = w.actor(s, "central_op")
        with pytest.raises(own.OfficeRequired) as exc:
            own.stop_watching(s, actor, op, case, reason="not ours")
        assert sorted(exc.value.candidates) == ["EDU", "HEALTH"]
        flags = own.available_actions(s, op, case)
        assert flags["stop_watching"] is True and flags["stop_watching_departments"] == ["EDU", "HEALTH"]
        row = own.stop_watching(s, actor, op, case, reason="not ours", office_code="HEALTH")
        assert row.office_id == w.offices["HEALTH"].id and row.status == OwnershipStatus.RELEASED
        assert _row(s, w, case, "EDU") is not None
        audit = _audit(s, case, "ownership.unwatch")
        assert audit.after["office_code"] == "HEALTH" and audit.actor_office_code == "HEALTH"
        with pytest.raises(own.OwnershipError, match="no membership in REV"):
            own.stop_watching(s, actor, op, case, reason="r", office_code="REV")


def test_request_transfer_from_primary_and_watcher_member(dual):
    """Decision 3: the EDU admin (primary membership EDU, a watcher) also works in HEALTH (the primary owner):
    the transfer is requested from HEALTH; before, EDU acted and the answer was `not_primary`."""
    w = dual
    with w.Session() as s:
        case = make_case(s)
        h_actor, h_admin = w.actor(s, "health_admin")
        own.claim(s, h_actor, h_admin, case)
        recommend(s, w, case, "EDU")
        actor, person = w.actor(s, "edu_admin")
        own.claim(s, actor, person, case, office_code="EDU")
        # without cases.transfer_request in HEALTH: 403, never a transfer from EDU
        with pytest.raises(access.Forbidden):
            own.request_transfer(s, actor, person, case, to_office_code="EDU", reason="ours")
        _grant(s, w, [Permission.CASES_TRANSFER_REQUEST])
        with pytest.raises(own.OwnershipError, match="another department"):
            own.request_transfer(s, actor, person, case, to_office_code="HEALTH", reason="r")
        t = own.request_transfer(s, actor, person, case, to_office_code="EDU", reason="ours")
        assert t.from_office_id == w.offices["HEALTH"].id and t.to_office_id == w.offices["EDU"].id
        audit = _audit(s, case, "transfer.request")
        assert audit.after["from_office_code"] == "HEALTH" and audit.actor_office_code == "HEALTH"


def test_request_transfer_watcher_only_still_not_primary(dual):
    w = dual
    with w.Session() as s:
        case = make_case(s)
        h_actor, h_admin = w.actor(s, "health_admin")
        own.claim(s, h_actor, h_admin, case)
        recommend(s, w, case, "EDU")
        e_actor, e_admin = w.actor(s, "edu_head")
        own.claim(s, *w.actor(s, "edu_admin"), case, office_code="EDU")
        with pytest.raises(own.OwnershipConflict) as exc:
            own.request_transfer(s, e_actor, e_admin, case, to_office_code="HEALTH", reason="r")
        assert exc.value.code == "not_primary"


def test_api_suggest_takeover_stopwatching_take_office_code(dual, api):
    w = dual
    with w.Session() as s:
        _grant(s, w, [Permission.CASES_SUGGEST_ELSEWHERE])
        rec_case = make_case(s)
        recommend(s, w, rec_case, "EDU")
        health_rec = recommend(s, w, rec_case, "HEALTH")
        held = _held_and_allotted(s, w)
        watched = _watched_from_both(s, w)
        ids = {k: str(v.id) for k, v in (("rec", rec_case), ("held", held), ("watched", watched))}
        health_rec_id = health_rec.id
        health_off = str(w.users["health_off"].id)
        s.commit()
    h = bearer(api, USERS["edu_admin"][0], PW)
    r = api.post(
        f"/cases/{ids['rec']}/suggest",
        json={"office_code": "EDU", "reason": "education", "from_office_code": "HEALTH"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["own"]["office_code"] == "HEALTH"
    r = api.post(
        f"/cases/{ids['rec']}/suggest",
        json={"office_code": "HEALTH", "reason": "r", "from_office_code": "CENTRAL"},
        headers=h,
    )
    assert r.status_code == 400
    r = api.get(f"/cases/{ids['held']}/ownership", headers=h)
    assert r.status_code == 200, r.text
    actions = r.json()["actions"]
    assert actions["take_over_departments"] == ["EDU", "HEALTH"]
    assert actions["allot_departments"] == ["EDU", "HEALTH"] and actions["transfer_from"] == "EDU"
    r = api.post(
        f"/cases/{ids['held']}/take-over",
        json={"office_code": "HEALTH", "expected_officer_user_id": health_off},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["office_code"] == "HEALTH" and r.json()["taken_from"]["id"] == health_off
    r = api.post(f"/cases/{ids['held']}/take-over", json={"office_code": "x" * 41}, headers=h)
    assert r.status_code == 422
    op = bearer(api, USERS["central_op"][0], PW)
    r = api.post(f"/cases/{ids['watched']}/stop-watching", json={"reason": "not ours"}, headers=op)
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "office_required"
    assert sorted(r.json()["detail"]["candidates"]) == ["EDU", "HEALTH"]
    r = api.post(
        f"/cases/{ids['watched']}/stop-watching",
        json={"reason": "not ours", "office_code": "EDU"},
        headers=op,
    )
    assert r.status_code == 200, r.text
    assert r.json()["office_code"] == "EDU" and r.json()["status"] == "released"
    with w.Session() as s:
        assert s.get(Recommendation, health_rec_id).status == RecommendationStatus.SUGGESTED_ELSEWHERE
