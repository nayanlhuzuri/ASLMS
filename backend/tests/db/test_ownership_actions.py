"""The `actions` block of `GET /cases/{ref}/ownership` (design `portal-cases`, decision 14c): each flag is true
exactly when the action itself would succeed (or only ask which department acts), the claim departments, the
super admin's null list, and that reading the flags writes nothing and keeps a hidden case hidden."""

from __future__ import annotations

from collections.abc import Callable

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from aslms.api.main import create_app
from aslms.core.config import Settings
from aslms.domain.events import AuditLog, Event
from aslms.domain.ownership import (
    CaseOwnership,
    OwnershipTransfer,
    Recommendation,
    RecommendationOrigin,
    ScoreBand,
)
from aslms.domain.reference import Role
from aslms.services import access
from aslms.services import ownership as own
from tests.db.auth_support import bearer
from tests.db.world import PW, USERS, add_membership, make_case

DEPARTMENTS = ("EDU", "HEALTH")
FLAGS = (
    "dismiss",
    "suggest",
    "allot",
    "take_over",
    "stop_watching",
    "request_transfer",
    "withdraw_transfer",
    "decide_transfer",
)


def recommend(s, world, case, code):
    rec = Recommendation(
        case_id=case.id,
        office_id=world.offices[code].id,
        score=0.95,
        band=ScoreBand.HIGH,
        origin=RecommendationOrigin.CAUSE_LIST,
        actor_name="matching",
    )
    s.add(rec)
    s.flush()
    return rec


def build_states(s, world) -> dict[str, object]:
    """The case states of the outcome test, built through the services."""
    a_edu, u_edu = world.actor(s, "edu_admin")
    a_health, u_health = world.actor(s, "health_admin")
    states: dict[str, object] = {}
    states["pool"] = make_case(s)
    rec_case = make_case(s)
    recommend(s, world, rec_case, "EDU")
    states["recommended_edu"] = rec_case
    owned = make_case(s)
    own.claim(s, a_edu, u_edu, owned, officer_user_id=world.users["edu_off1"].id)
    states["owned_edu_allotted"] = owned
    watched = make_case(s)
    own.claim(s, a_health, u_health, watched)
    recommend(s, world, watched, "EDU")
    own.claim(s, a_edu, u_edu, watched)
    states["owned_health_edu_watching"] = watched
    out_ = make_case(s)
    own.claim(s, a_edu, u_edu, out_)
    own.request_transfer(s, a_edu, u_edu, out_, to_office_code="HEALTH", reason="theirs")
    states["transfer_edu_to_health"] = out_
    in_ = make_case(s)
    own.claim(s, a_health, u_health, in_)
    own.request_transfer(s, a_health, u_health, in_, to_office_code="EDU", reason="yours")
    states["transfer_health_to_edu"] = in_
    s.flush()
    return states


def outcome(s, run: Callable[[], object], *, also_ok: Callable[[Exception], bool] = lambda e: False) -> bool:
    """Runs one action in a savepoint that is rolled back: True when it succeeds or answers only
    `office_required` (or a refusal `also_ok` accepts)."""
    sp = s.begin_nested()
    try:
        run()
        return True
    except own.OfficeRequired:
        return True
    except (access.Forbidden, own.OwnershipError) as exc:
        return also_ok(exc)
    finally:
        if sp.is_active:
            sp.rollback()
        s.expire_all()


def _target_specific(exc: Exception) -> bool:
    """`target_owns`: a refusal that depends only on the chosen target department, raised after every check of
    the caller's side (the flag leaves the target to the dialog)."""
    return isinstance(exc, own.OwnershipConflict) and exc.code == "target_owns"


def expected(s, world, key: str, case) -> dict[str, object]:
    actor, user = world.actor(s, key)
    open_t = s.scalar(
        sa.select(OwnershipTransfer).where(
            OwnershipTransfer.case_id == case.id, OwnershipTransfer.status == "requested"
        )
    )
    claim_ok = {
        code: outcome(s, lambda c=code: own.claim(s, actor, user, case, office_code=c))
        for code in DEPARTMENTS
    }
    out: dict[str, object] = {"claim_by_code": claim_ok}
    out["dismiss"] = outcome(s, lambda: own.dismiss(s, actor, user, case))
    out["suggest"] = any(
        outcome(
            s,
            lambda c=code: own.suggest(s, actor, user, case, office_code=c, reason="r"),
            also_ok=_target_specific,
        )
        for code in DEPARTMENTS
    )
    out["allot"] = outcome(s, lambda: own.allot(s, actor, user, case))
    out["take_over"] = outcome(s, lambda: own.take_over(s, actor, user, case))
    out["stop_watching"] = outcome(s, lambda: own.stop_watching(s, actor, user, case, reason="r"))
    out["request_transfer"] = any(
        outcome(s, lambda c=code: own.request_transfer(s, actor, user, case, to_office_code=c, reason="r"))
        for code in DEPARTMENTS
    )
    out["withdraw_transfer"] = open_t is not None and outcome(
        s, lambda: own.withdraw_transfer(s, actor, user, s.get(OwnershipTransfer, open_t.id))
    )
    out["decide_transfer"] = open_t is not None and outcome(
        s, lambda: own.decide_transfer(s, actor, user, s.get(OwnershipTransfer, open_t.id), accept=True)
    )
    return out


def test_actions_match_outcomes(world):
    mismatches = []
    with world.Session() as s:
        states = build_states(s, world)
        for key in USERS:
            for state, case in states.items():
                user = world.user(s, key)
                flags = own.available_actions(s, user, case)
                exp = expected(s, world, key, case)
                for flag in FLAGS:
                    if flags[flag] != exp[flag]:
                        mismatches.append((key, state, flag, flags[flag], exp[flag]))
                by_code = exp["claim_by_code"]
                if key == "root":
                    if flags["claim_departments"] is not None or flags["claim"] != any(by_code.values()):
                        mismatches.append((key, state, "claim", flags, by_code))
                else:
                    mine = {m.department.code for m in access.members(s, user) if m.department is not None}
                    want = sorted(c for c, ok in by_code.items() if ok and c in mine)
                    if sorted(flags["claim_departments"]) != want or flags["claim"] != bool(want):
                        mismatches.append((key, state, "claim", flags["claim_departments"], want))
        s.rollback()
    assert not mismatches, "; ".join(map(str, mismatches))


def test_claim_departments_lists_qualifying_memberships(world):
    with world.Session() as s:
        add_membership(s, world.user(s, "edu_admin"), world.office(s, "HEALTH"), Role.DEPT_OFFICER)
        case = make_case(s)
        s.flush()
        flags = own.available_actions(s, world.user(s, "edu_admin"), case)
        assert flags["claim"] is True and flags["claim_departments"] == ["EDU"]
        # an officer of HEALTH only: no claim anywhere
        flags = own.available_actions(s, world.user(s, "health_off"), case)
        assert flags["claim"] is False and flags["claim_departments"] == []
        s.rollback()


def test_claim_departments_null_for_super_admin(world):
    with world.Session() as s:
        case = make_case(s)
        s.flush()
        flags = own.available_actions(s, world.user(s, "root"), case)
        assert flags["claim"] is True and flags["claim_departments"] is None
        # once EDU owns it and nobody else is recommended, no department may claim it
        actor, user = world.actor(s, "edu_admin")
        own.claim(s, actor, user, case)
        flags = own.available_actions(s, world.user(s, "root"), case)
        assert flags["claim"] is False and flags["claim_departments"] is None
        recommend(s, world, case, "HEALTH")
        assert own.available_actions(s, world.user(s, "root"), case)["claim"] is True
        s.rollback()


def test_officer_without_ownership_functions_has_no_actions(world):
    with world.Session() as s:
        states = build_states(s, world)
        for case in states.values():
            flags = own.available_actions(s, world.user(s, "edu_reviewer"), case)
            assert flags["claim_departments"] == []
            assert not any(v for k, v in flags.items() if k != "claim_departments"), flags
        s.rollback()


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


def test_actions_write_nothing(api, world):
    headers = bearer(api, USERS["edu_admin"][0], PW)  # signing in writes its own rows; count after it
    with world.Session() as s:
        case = make_case(s)
        recommend(s, world, case, "EDU")
        s.commit()
        ref = case.ref_no.replace("/", "-")
        counts_before = [s.scalar(sa.select(sa.func.count()).select_from(m)) for m in (AuditLog, Event)]
        owners_before = s.scalar(sa.select(sa.func.count()).select_from(CaseOwnership))
    r = api.get(f"/cases/{ref}/ownership", headers=headers)
    assert r.status_code == 200, r.text
    actions = r.json()["actions"]
    assert actions["claim"] is True and actions["claim_departments"] == ["EDU"]
    assert actions["dismiss"] is True and actions["suggest"] is True
    assert (
        actions["allot"] is False and actions["take_over"] is False and actions["request_transfer"] is False
    )
    with world.Session() as s:
        assert [
            s.scalar(sa.select(sa.func.count()).select_from(m)) for m in (AuditLog, Event)
        ] == counts_before
        assert s.scalar(sa.select(sa.func.count()).select_from(CaseOwnership)) == owners_before


def test_actions_ignore_hidden_case(api, world):
    with world.Session() as s:
        case = make_case(s)
        actor, user = world.actor(s, "health_admin")
        own.claim(s, actor, user, case)
        s.commit()
        ref = case.ref_no.replace("/", "-")
    r = api.get(f"/cases/{ref}/ownership", headers=bearer(api, USERS["edu_admin"][0], PW))
    assert r.status_code == 404
    r = api.get(f"/cases/{ref}/ownership", headers=bearer(api, USERS["health_admin"][0], PW))
    assert r.status_code == 200 and r.json()["actions"]["request_transfer"] is True
    assert r.json()["actions"]["claim"] is False
