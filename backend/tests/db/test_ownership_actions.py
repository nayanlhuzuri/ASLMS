"""The `actions` block of `GET /cases/{ref}/ownership` (design `portal-cases`, decision 14c, and
`portal-cases-followups`, decisions 1, 3 and 7): each flag is true exactly when the action itself would succeed
for some department, each department list names exactly the caller's departments for which the action succeeds
with that department named, `transfer_from` is the primary owner's department, the super admin's claim list
is null only for a pool case, and reading the flags writes nothing and keeps a hidden case hidden."""

from __future__ import annotations

from collections.abc import Callable

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from aslms.api.main import create_app
from aslms.core.config import Settings
from aslms.domain.events import AuditLog, Event
from aslms.domain.org import PermissionEffect
from aslms.domain.ownership import (
    CaseOwnership,
    OwnershipTransfer,
    Recommendation,
    RecommendationOrigin,
    ScoreBand,
)
from aslms.domain.reference import Permission, Role
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


def outcome(
    s,
    run: Callable[[], object],
    *,
    also_ok: Callable[[Exception], bool] = lambda e: False,
    strict: bool = False,
) -> bool:
    """Runs one action in a savepoint that is rolled back: True when it succeeds or answers only
    `office_required` (unless `strict`), or a refusal `also_ok` accepts."""
    sp = s.begin_nested()
    try:
        run()
        return True
    except own.OfficeRequired:
        return not strict
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


def own_departments(s, user) -> list[str]:
    out: list[str] = []
    for m in access.members(s, user):
        if m.department is not None and m.department.code not in out:
            out.append(m.department.code)
    return out


def expected(s, world, key: str, case) -> dict[str, object]:
    actor, user = world.actor(s, key)
    mine = own_departments(s, user)

    def some_department(run: Callable[[str], object]) -> bool:
        """The action succeeds for one of the caller's departments, named (decision 1)."""
        return any(outcome(s, lambda c=c: run(c), strict=True) for c in mine)

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
    out["dismiss"] = some_department(lambda c: own.dismiss(s, actor, user, case, office_code=c))
    out["suggest"] = any(
        outcome(
            s,
            lambda c=code: own.suggest(s, actor, user, case, office_code=c, reason="r"),
            also_ok=_target_specific,
        )
        for code in DEPARTMENTS
    )
    out["allot"] = some_department(lambda c: own.allot(s, actor, user, case, office_code=c))
    out["take_over"] = some_department(lambda c: own.take_over(s, actor, user, case, office_code=c))
    out["stop_watching"] = some_department(
        lambda c: own.stop_watching(s, actor, user, case, reason="r", office_code=c)
    )
    out["request_transfer"] = any(
        outcome(
            s,
            lambda c=code: own.request_transfer(s, actor, user, case, to_office_code=c, reason="r"),
            strict=True,
        )
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
                    want_root = sorted(c for c, ok in by_code.items() if ok)
                    if not own.ever_owned(s, case):
                        ok_root = flags["claim_departments"] is None and flags["claim"] == bool(want_root)
                    else:
                        ok_root = flags["claim_departments"] == want_root and flags["claim"] == bool(
                            want_root
                        )
                    if not ok_root:
                        mismatches.append((key, state, "claim", flags["claim_departments"], want_root))
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


def test_super_admin_claim_departments_null_for_pool_case(world):
    with world.Session() as s:
        case = make_case(s)
        recommend(s, world, case, "HEALTH")
        s.flush()
        flags = own.available_actions(s, world.user(s, "root"), case)
        assert flags["claim"] is True and flags["claim_departments"] is None
        s.rollback()


def test_super_admin_claim_departments_lists_recommended_not_holding(world):
    with world.Session() as s:
        case = make_case(s)
        actor, user = world.actor(s, "edu_admin")
        own.claim(s, actor, user, case)
        # claimed by EDU, nobody else recommended: no department may claim it
        flags = own.available_actions(s, world.user(s, "root"), case)
        assert flags["claim"] is False and flags["claim_departments"] == []
        recommend(s, world, case, "HEALTH")
        flags = own.available_actions(s, world.user(s, "root"), case)
        assert flags["claim"] is True and flags["claim_departments"] == ["HEALTH"]
        # the listed department claims (as watcher); then it holds the case and the list is empty again
        r_actor, root = world.actor(s, "root")
        own.claim(s, r_actor, root, case, office_code="HEALTH")
        flags = own.available_actions(s, world.user(s, "root"), case)
        assert flags["claim"] is False and flags["claim_departments"] == []
        s.rollback()


LISTS = {
    "dismiss_departments": lambda s, a, u, case, c: own.dismiss(s, a, u, case, office_code=c),
    "allot_departments": lambda s, a, u, case, c: own.allot(s, a, u, case, office_code=c),
    "take_over_departments": lambda s, a, u, case, c: own.take_over(s, a, u, case, office_code=c),
    "stop_watching_departments": lambda s, a, u, case, c: own.stop_watching(
        s, a, u, case, reason="r", office_code=c
    ),
}


def _two_department_world(s, world):
    """The EDU admin also works in HEALTH as an officer granted the ownership functions there, so the lists
    can hold two codes."""
    add_membership(s, world.user(s, "edu_admin"), world.office(s, "HEALTH"), Role.DEPT_OFFICER)
    s.flush()
    h_actor, h_admin = world.actor(s, "health_admin")
    health_m = world.membership(s, "edu_admin", "HEALTH")
    for perm in (
        Permission.CASES_DISMISS,
        Permission.CASES_ALLOT,
        Permission.CASES_RELEASE,
        Permission.CASES_SUGGEST_ELSEWHERE,
        Permission.CASES_CLAIM,
    ):
        access.set_override(s, h_actor, h_admin, health_m, perm, PermissionEffect.GRANT)
    s.flush()


def expected_lists(s, world, key: str, case) -> dict[str, list[str]]:
    """Per list, the caller's departments for which the action succeeds with that department named."""
    actor, user = world.actor(s, key)
    mine = own_departments(s, user)
    out = {
        name: [c for c in mine if outcome(s, lambda c=c, run=run: run(s, actor, user, case, c), strict=True)]
        for name, run in LISTS.items()
    }
    out["suggest_departments"] = [
        c
        for c in mine
        if any(
            outcome(
                s,
                lambda c=c, t=t: own.suggest(
                    s, actor, user, case, office_code=t, reason="r", from_office_code=c
                ),
                also_ok=_target_specific,
                strict=True,
            )
            for t in DEPARTMENTS
            if t != c
        )
    ]
    return out


def test_department_lists_match_outcomes(world):
    mismatches = []
    with world.Session() as s:
        _two_department_world(s, world)
        states = build_states(s, world)
        both = make_case(s)
        recommend(s, world, both, "EDU")
        recommend(s, world, both, "HEALTH")
        states["recommended_both"] = both
        held_both = make_case(s)
        a_edu, u_edu = world.actor(s, "edu_admin")
        own.claim(s, a_edu, u_edu, held_both, office_code="EDU", officer_user_id=world.users["edu_off1"].id)
        recommend(s, world, held_both, "HEALTH")
        own.claim(s, *world.actor(s, "health_admin"), held_both)
        own.allot(s, *world.actor(s, "health_admin"), held_both, officer_user_id=world.users["health_off"].id)
        states["held_edu_watched_health_allotted"] = held_both
        s.flush()
        for key in USERS:
            for state, case in states.items():
                flags = own.available_actions(s, world.user(s, key), case)
                for name, want in expected_lists(s, world, key, case).items():
                    if flags[name] != want:
                        mismatches.append((key, state, name, flags[name], want))
        # the two-department login sees both codes where both departments qualify
        flags = own.available_actions(s, world.user(s, "edu_admin"), both)
        assert flags["dismiss_departments"] == ["EDU", "HEALTH"] and flags["dismiss"] is True
        assert flags["suggest_departments"] == ["EDU", "HEALTH"]
        flags = own.available_actions(s, world.user(s, "edu_admin"), held_both)
        assert flags["allot_departments"] == ["EDU", "HEALTH"]
        assert flags["take_over_departments"] == ["EDU", "HEALTH"]
        assert flags["stop_watching_departments"] == ["HEALTH"] and flags["transfer_from"] == "EDU"
        s.rollback()
    assert not mismatches, "; ".join(map(str, mismatches))


def test_transfer_from_is_primary_department(world):
    """Decision 3: a login in both the primary department (HEALTH) and a watcher department (EDU, its primary
    membership) requests the transfer from the primary department."""
    with world.Session() as s:
        _two_department_world(s, world)
        h_actor, h_admin = world.actor(s, "health_admin")
        access.set_override(
            s,
            h_actor,
            h_admin,
            world.membership(s, "edu_admin", "HEALTH"),
            Permission.CASES_TRANSFER_REQUEST,
            PermissionEffect.GRANT,
        )
        case = make_case(s)
        own.claim(s, h_actor, h_admin, case)
        recommend(s, world, case, "EDU")
        actor, user = world.actor(s, "edu_admin")
        own.claim(s, actor, user, case, office_code="EDU")
        flags = own.available_actions(s, user, case)
        assert flags["request_transfer"] is True and flags["transfer_from"] == "HEALTH"
        # an EDU officer (the watcher department only): no transfer
        flags = own.available_actions(s, world.user(s, "edu_off1"), case)
        assert flags["request_transfer"] is False and flags["transfer_from"] is None
        # the primary department's own admin
        assert own.available_actions(s, h_admin, case)["transfer_from"] == "HEALTH"
        s.rollback()


def test_officer_without_ownership_functions_has_no_actions(world):
    with world.Session() as s:
        states = build_states(s, world)
        for case in states.values():
            flags = own.available_actions(s, world.user(s, "edu_reviewer"), case)
            assert flags["claim_departments"] == []
            assert not any(flags.values()), flags
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
    assert actions["dismiss_departments"] == ["EDU"] and actions["suggest_departments"] == ["EDU"]
    assert actions["allot_departments"] == [] and actions["take_over_departments"] == []
    assert actions["stop_watching_departments"] == [] and actions["transfer_from"] is None
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
