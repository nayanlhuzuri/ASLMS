"""The one visibility rule (design cases-api, decisions 1–3): every basis evaluated for the shared world —
State-wide readers, owner and watcher, recommended, pool, allotted (officer and directorate), a transfer with
and without `stay_as_watcher`, custody (office-wide and personal: the holder membership, design
custody-workflow), the standing counsel's codes, a denied `cases.view_scope`, and the list-equals-detail check through
the API (`GET /cases` returns exactly the cases `can_view_case` admits; `/cases/search` marks exactly those
visible)."""

from __future__ import annotations

from datetime import date

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from aslms.api.main import create_app
from aslms.core.config import Settings
from aslms.domain.cases import AdvocateSide, CaseAdvocate, CaseStatus
from aslms.domain.causelists import Causelist, CauselistEntry, EntrySource, ListSource, ListType
from aslms.domain.courts import Court
from aslms.domain.org import PermissionEffect
from aslms.domain.ownership import (
    CounselCode,
    Recommendation,
    RecommendationOrigin,
    ScoreBand,
    TransferStatus,
)
from aslms.domain.reference import Permission
from aslms.domain.workflow import Custody
from aslms.services import access
from aslms.services import ownership as own
from aslms.services import visibility as vis
from aslms.services.cases import refresh_search_vector
from tests.db.auth_support import bearer
from tests.db.world import PW, USERS, make_case

# ------------------------------------------------------------------------------------------------ helpers


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


def claim(s, world, key, case, **kw):
    actor, user = world.actor(s, key)
    return own.claim(s, actor, user, case, **kw)


def custody_at(s, case, office, user=None):
    """A custody row as `move_custody` writes it: a person holds through their membership (custody-workflow)."""
    membership = None
    if user is not None:
        member = next((m for m in access.members(s, user) if m.covers(office)), None)
        membership = (member or access.primary_member(s, user)).membership
    row = Custody(
        case_id=case.id,
        holder_office_id=office.id,
        holder_user_id=user.id if user else None,
        holder_membership_id=membership.id if membership else None,
    )
    s.add(row)
    s.flush()
    return row


def entry_with_codes(s, case, codes, *, pet="RAM KUMAR", list_date=date(2025, 1, 6)):
    court = s.scalar(sa.select(Court).where(Court.est_code == "GAHC01"))
    cl = s.scalar(
        sa.select(Causelist).where(
            Causelist.list_date == list_date, Causelist.source == ListSource.GHC_WEBSITE
        )
    )
    if cl is None:
        cl = Causelist(
            court_id=court.id, list_date=list_date, list_type=ListType.DAILY, source=ListSource.GHC_WEBSITE
        )
        s.add(cl)
        s.flush()
    n = int(s.scalar(sa.select(sa.func.count()).select_from(CauselistEntry)) or 0) + 1
    e = CauselistEntry(
        causelist_id=cl.id,
        sr_no=n,
        cnr=case.cnr,
        case_id=case.id,
        case_no_text=case.case_no_text,
        petitioner_text=pet,
        respondent_text="THE STATE OF ASSAM",
        counsel_codes=list(codes),
        source=EntrySource.PDF_PARSE,
    )
    s.add(e)
    s.flush()
    return e


def sees(s, world, key, case) -> bool:
    return vis.can_view_case(s, world.user(s, key), case)


def basis(s, world, key, case) -> list[str]:
    return vis.access_basis(s, world.user(s, key), case)


# ------------------------------------------------------------------------------------------------ state readers


def test_state_wide_readers_see_everything_on_the_state_basis(world):
    with world.Session() as s:
        a = make_case(s)
        b = make_case(s, status=CaseStatus.DISPOSED)
        claim(s, world, "health_admin", a)
        s.flush()
        for key in ("root", "oversight", "edu_auditor", "central_op"):
            assert basis(s, world, key, a) == ["state"], key
            assert basis(s, world, key, b) == ["state"], key
        # the department users of EDU do not see HEALTH's case
        assert not sees(s, world, "edu_admin", a) and not sees(s, world, "edu_head", a)
        assert not sees(s, world, "edu_off1", a) and not sees(s, world, "dse_user", a)
        s.rollback()


# ------------------------------------------------------------------------------------------------ owner / recommended / pool


def test_department_wide_callers_owner_recommended_and_pool(world):
    with world.Session() as s:
        owned = make_case(s)
        watched = make_case(s)
        recommended = make_case(s)
        pool = make_case(s)
        other = make_case(s)
        claim(s, world, "edu_admin", owned)
        claim(s, world, "health_admin", watched)
        recommend(s, world, watched, "EDU")
        claim(s, world, "edu_admin", watched)  # EDU is a watcher of HEALTH's case
        recommend(s, world, recommended, "EDU")
        claim(s, world, "health_admin", other)
        s.flush()
        for key in ("edu_admin", "edu_head"):
            assert "owner" in basis(s, world, key, owned), key
            assert "owner" in basis(s, world, key, watched), key
            assert basis(s, world, key, recommended) == ["recommended", "pool"], key  # never owned
            assert basis(s, world, key, pool) == ["pool"], key
            assert not sees(s, world, key, other), key
        # the pool case is a summary only for an officer (no cases.claim) — not visible
        assert not sees(s, world, "edu_off1", pool)
        assert not sees(s, world, "dse_user", pool)
        assert sees(s, world, "edu_admin", pool)
        # a pool case never owned: HEALTH's admin sees it too (any department may claim it)
        assert basis(s, world, "health_admin", pool) == ["pool"]
        s.rollback()


# ------------------------------------------------------------------------------------------------ allotted


def test_allotment_scopes_officers_and_directorate_users(world):
    with world.Session() as s:
        to_off1 = make_case(s)
        to_off2 = make_case(s)
        to_dse = make_case(s)
        to_dhe = make_case(s)
        off1, off2 = world.user(s, "edu_off1"), world.user(s, "edu_off2")
        claim(s, world, "edu_admin", to_off1, officer_user_id=off1.id)
        claim(s, world, "edu_admin", to_off2, officer_user_id=off2.id)
        claim(s, world, "edu_admin", to_dse, unit_code="EDU-DSE")
        claim(s, world, "edu_admin", to_dhe, unit_code="EDU-DHE")
        s.flush()
        # allotment also moves custody to the officer / unit, so both bases name the case
        assert basis(s, world, "edu_off1", to_off1) == ["allotted", "custody"]
        assert not sees(s, world, "edu_off1", to_off2)
        assert not sees(s, world, "edu_off1", to_dse)
        assert basis(s, world, "dse_user", to_dse) == ["allotted", "custody"]
        assert not sees(s, world, "dse_user", to_dhe)
        assert not sees(s, world, "dse_user", to_off1)
        assert basis(s, world, "dhe_user", to_dhe) == ["allotted", "custody"]
        # the department-wide callers see all four as owner
        for c in (to_off1, to_off2, to_dse, to_dhe):
            assert "owner" in basis(s, world, "edu_head", c)
        s.rollback()


# ------------------------------------------------------------------------------------------------ transfers


@pytest.mark.parametrize("stay", [False, True])
def test_transfer_away_ends_sight_unless_watcher(world, stay):
    with world.Session() as s:
        case = make_case(s)
        claim(s, world, "edu_admin", case)
        actor, admin = world.actor(s, "edu_admin")
        t = own.request_transfer(
            s, actor, admin, case, to_office_code="HEALTH", reason="theirs", stay_as_watcher=stay
        )
        h_actor, h_admin = world.actor(s, "health_admin")
        own.decide_transfer(s, h_actor, h_admin, t, accept=True)
        s.flush()
        assert t.status == TransferStatus.ACCEPTED
        assert "owner" in basis(s, world, "health_admin", case)
        assert sees(s, world, "edu_admin", case) is stay
        assert sees(s, world, "edu_head", case) is stay
        s.rollback()


# ------------------------------------------------------------------------------------------------ custody


def test_custody_office_wide_for_units_and_personal_for_officers(world):
    with world.Session() as s:
        at_dse = make_case(s)
        with_off2 = make_case(s)
        custody_at(s, at_dse, world.office(s, "EDU-DSE"))
        custody_at(s, with_off2, world.office(s, "EDU"), world.user(s, "edu_off2"))
        assert basis(s, world, "dse_user", at_dse) == ["custody"]
        assert not sees(s, world, "dhe_user", at_dse)
        assert basis(s, world, "edu_off2", with_off2) == ["custody"]
        assert not sees(s, world, "edu_off1", with_off2)
        # the department-wide caller sees both (department subtree); never owned, they are in the pool too
        assert basis(s, world, "edu_admin", at_dse) == ["pool", "custody"]
        assert basis(s, world, "edu_admin", with_off2) == ["pool", "custody"]
        # a custody row at HEALTH says nothing to EDU
        at_health = make_case(s)
        claim(s, world, "health_admin", at_health)  # out of the pool, held by HEALTH
        assert not sees(s, world, "edu_admin", at_health)
        s.rollback()


def test_personal_custody_follows_the_holder_membership(world):
    """custody-workflow decision 9: a referral reviewer (personal basis) sees a file only while their own
    membership holds it; an office-held leg at EDU says nothing to them."""
    with world.Session() as s:
        edu = world.office(s, "EDU")
        personal_case, office_case = make_case(s), make_case(s)
        custody_at(s, personal_case, edu, world.user(s, "edu_reviewer"))
        custody_at(s, office_case, edu)
        assert basis(s, world, "edu_reviewer", personal_case) == ["custody"]
        assert not sees(s, world, "edu_reviewer", office_case)
        assert "request" not in {name for name, _ in vis.visibility_bases(s, world.user(s, "edu_admin"))}
        s.rollback()


# ------------------------------------------------------------------------------------------------ counsel


def test_standing_counsel_sees_cases_carrying_the_department_codes(world):
    with world.Session() as s:
        s.add(CounselCode(code="SC, EDU", office_id=world.office(s, "EDU-DSE").id))
        s.add(CounselCode(code="PP, ASSAM", office_id=world.office(s, "GOA").id, is_generic_state=True))
        s.add(CounselCode(code="SC, HEALTH", office_id=world.office(s, "HEALTH").id))
        s.flush()
        by_entry = make_case(s)
        entry_with_codes(s, by_entry, ["SC,EDU"])  # unnormalised, as printed
        generic = make_case(s)
        entry_with_codes(s, generic, ["PP, ASSAM"])
        health = make_case(s)
        entry_with_codes(s, health, ["SC, HEALTH"])
        by_adv = make_case(s)
        s.add(
            CaseAdvocate(
                case_id=by_adv.id,
                side=AdvocateSide.RESPONDENT,
                name_as_listed="SC, EDU",
                counsel_code="SC, EDU",
            )
        )
        former = make_case(s)
        s.add(
            CaseAdvocate(
                case_id=former.id,
                side=AdvocateSide.RESPONDENT,
                name_as_listed="SC, EDU",
                counsel_code="SC, EDU",
                is_current=False,
            )
        )
        s.flush()
        assert basis(s, world, "edu_counsel", by_entry) == ["counsel"]
        assert basis(s, world, "edu_counsel", by_adv) == ["counsel"]
        assert not sees(s, world, "edu_counsel", generic)
        assert not sees(s, world, "edu_counsel", health)
        assert not sees(s, world, "edu_counsel", former)
        # the counsel's other bases still apply (allotted to the EDU-SC unit)
        allotted = make_case(s)
        claim(s, world, "edu_admin", allotted, unit_code="EDU-SC")
        assert basis(s, world, "edu_counsel", allotted) == ["allotted", "custody"]
        # a deactivated code stops matching
        code = s.scalar(sa.select(CounselCode).where(CounselCode.code == "SC, EDU"))
        code.is_active = False
        s.flush()
        assert not sees(s, world, "edu_counsel", by_entry)
        s.rollback()


# ------------------------------------------------------------------------------------------------ denied scope


def test_denied_view_scope_sees_nothing(world):
    with world.Session() as s:
        case = make_case(s)
        off1 = world.user(s, "edu_off1")
        claim(s, world, "edu_admin", case, officer_user_id=off1.id)
        assert sees(s, world, "edu_off1", case)
        actor, root = world.actor(s, "root")
        access.set_override(s, actor, root, off1, Permission.CASES_VIEW_SCOPE, PermissionEffect.DENY)
        s.expire_all()
        off1 = world.user(s, "edu_off1")
        assert vis.visibility_bases(s, off1) == []
        assert not vis.can_view_case(s, off1, case)
        s.rollback()


def test_unknown_case_and_merged_case(world):
    with world.Session() as s:
        import uuid

        assert vis.access_basis(s, world.user(s, "root"), uuid.uuid4()) == []
        main = make_case(s)
        merged = make_case(s)
        claim(s, world, "edu_admin", merged)
        merged.merged_into_case_id = main.id
        s.flush()
        assert "owner" in basis(s, world, "edu_admin", merged)  # evaluated on the merged case itself
        s.rollback()


# ------------------------------------------------------------------------------------------------ one rule (API)


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


def test_list_and_search_follow_can_view_case_for_every_user(api, world):
    """Twelve cases covering every basis; for every world user `GET /cases` returns exactly the cases
    `can_view_case` admits and `/cases/search` marks exactly those `visible`."""
    with world.Session() as s:
        s.add(CounselCode(code="SC, EDU", office_id=world.office(s, "EDU-DSE").id))
        s.flush()
        edu, dhe, dse = world.office(s, "EDU"), world.office(s, "EDU-DHE"), world.office(s, "EDU-DSE")
        cases = {}
        cases["edu_owned"] = make_case(s, pet="STATE OF ASSAM EDU")
        claim(s, world, "edu_admin", cases["edu_owned"])
        cases["health_owned"] = make_case(s, pet="STATE OF ASSAM HEALTH")
        claim(s, world, "health_admin", cases["health_owned"])
        cases["edu_recommended"] = make_case(s, pet="STATE OF ASSAM REC")
        recommend(s, world, cases["edu_recommended"], "EDU")
        cases["pool"] = make_case(s, pet="STATE OF ASSAM POOL")
        cases["to_off1"] = make_case(s, pet="STATE OF ASSAM OFF1")
        claim(s, world, "edu_admin", cases["to_off1"], officer_user_id=world.user(s, "edu_off1").id)
        cases["to_dse"] = make_case(s, pet="STATE OF ASSAM DSE")
        claim(s, world, "edu_admin", cases["to_dse"], unit_code="EDU-DSE")
        cases["custody_dhe"] = make_case(s, pet="STATE OF ASSAM CUST")
        custody_at(s, cases["custody_dhe"], dhe)
        cases["custody_off2"] = make_case(s, pet="STATE OF ASSAM CUST2")
        custody_at(s, cases["custody_off2"], edu, world.user(s, "edu_off2"))
        cases["custody_dse"] = make_case(s, pet="STATE OF ASSAM REQ")
        custody_at(s, cases["custody_dse"], dse)
        cases["custody_reviewer"] = make_case(s, pet="STATE OF ASSAM REV")
        custody_at(s, cases["custody_reviewer"], edu, world.user(s, "edu_reviewer"))
        cases["counsel"] = make_case(s, pet="STATE OF ASSAM SC")
        entry_with_codes(s, cases["counsel"], ["SC, EDU"], pet="STATE OF ASSAM SC")
        claim(s, world, "health_admin", cases["counsel"])
        cases["disposed_edu"] = make_case(s, pet="STATE OF ASSAM DISP", status=CaseStatus.DISPOSED)
        claim(s, world, "edu_admin", cases["disposed_edu"])
        refresh_search_vector(s, [c.id for c in cases.values()])  # the pipeline does this after every write
        s.commit()
        expected = {
            key: {name for name, c in cases.items() if vis.can_view_case(s, world.user(s, key), c)}
            for key in USERS
        }
        ids = {str(c.id): name for name, c in cases.items()}
    assert expected["edu_off1"] == {"to_off1", "pool"} - {"pool"}
    assert expected["dse_user"] == {"to_dse", "custody_dse"}
    assert expected["edu_counsel"] == {"counsel"}
    assert expected["edu_reviewer"] == {"custody_reviewer"}
    assert expected["edu_admin"] >= {
        "edu_owned",
        "edu_recommended",
        "pool",
        "to_off1",
        "to_dse",
        "disposed_edu",
    }
    assert expected["root"] == set(cases)
    for key in USERS:
        headers = login(api, key)
        r = api.get("/cases?limit=200&case_state=all", headers=headers)
        assert r.status_code == 200, (key, r.text)
        listed = {ids[i["case"]["id"]] for i in r.json()["items"] if i["case"]["id"] in ids}
        assert listed == expected[key], key
        assert all(i["visible"] for i in r.json()["items"]), key
        r = api.get("/cases/search?q=STATE%20OF%20ASSAM&limit=200", headers=headers)
        assert r.status_code == 200, (key, r.text)
        rows = {ids[i["case"]["id"]]: i for i in r.json()["items"] if i["case"]["id"] in ids}
        assert set(rows) == set(cases), key  # every case is a summary in search
        assert {n for n, i in rows.items() if i["visible"]} == expected[key], key
        # details of a case outside the scope answer 404, inside 200 with the basis
        for name, c in cases.items():
            r = api.get(f"/cases/{c.id}", headers=headers)
            if name in expected[key]:
                assert r.status_code == 200 and r.json()["access_basis"], (key, name, r.text)
            else:
                assert r.status_code == 404, (key, name, r.status_code)
