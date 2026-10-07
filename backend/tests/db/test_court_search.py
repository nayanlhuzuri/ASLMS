"""Search the court and fetch a found case (design cases-api, decisions 9–14) against the scripted gateway:
the switch, local hits without a call, the CNR / case-number / party kinds, unmatched rows, fill-empty-only,
the quota floor, the per-user limit, a failing gateway recorded and audited, fetch-court on a party hit, a
provisional case resolved by number, 404 / 409 / 403."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from aslms.api.main import create_app
from aslms.core.config import Settings
from aslms.domain.cases import Case, CaseParty, FirstSeenSource
from aslms.domain.courts import CaseType, Court
from aslms.domain.events import AuditLog
from aslms.domain.ops import FetchKind, FetchQueueItem
from aslms.domain.ownership import CaseOfficeScore, OfficeKeyword
from aslms.services.audit import write_audit
from aslms.services.cases import apply_dossier
from tests.db.auth_support import bearer
from tests.db.conftest import sample
from tests.db.world import PW, USERS, make_case

WA_CNR = "GAHC010277142024"
PARTY_CNRS = {"GAHC010257252024", "GAHC010277142024", "GAHC010271682024"}


@pytest.fixture()
def api(world, napix, monkeypatch):
    """The app with the scripted NAPIX client injected and the switch reported as configured (the setting
    itself is never written: the property is patched for the test)."""
    gw, client, hc = napix
    monkeypatch.setattr(Settings, "napix_configured", property(lambda self: True))
    settings = Settings(
        _env_file=None,
        aslms_jwt_secret="test-secret-of-at-least-thirty-two-characters",
        aslms_access_token_minutes=5,
    )
    app = create_app(settings, world.Session)
    app.state.napix_factory = lambda: (client, hc)
    with TestClient(app) as c:
        c.gw = gw
        c.settings = settings
        yield c


@pytest.fixture()
def types(world):
    with world.Session() as s:
        court = s.scalar(sa.select(Court).where(Court.est_code == "GAHC01"))
        for code, short in ((111, "WP(C)"), (112, "WA"), (220, "I.A.(Civil)")):
            s.add(CaseType(court_id=court.id, case_type_code=code, type_name=short, short_name=short))
        s.commit()


def login(api: TestClient, key: str) -> dict:
    return bearer(api, USERS[key][0], PW)


def count(world, table: str, where: str = "true") -> int:
    with world.Session() as s:
        return int(s.execute(sa.text(f"select count(*) from {table} where {where}")).scalar())


def audits(world, action: str) -> list[AuditLog]:
    with world.Session() as s:
        return list(
            s.scalars(
                sa.select(AuditLog)
                .where(AuditLog.action == action)
                .order_by(AuditLog.created_at, AuditLog.id)
            )
        )


# ------------------------------------------------------------------------------------------------ the switch


def test_switch_off_answers_503_without_a_call(world, napix):
    gw, client, hc = napix
    settings = Settings(_env_file=None, aslms_jwt_secret="test-secret-of-at-least-thirty-two-characters")
    app = create_app(settings, world.Session)
    app.state.napix_factory = lambda: (client, hc)
    with TestClient(app) as api:
        r = api.post(
            "/cases/search-court",
            json={"kind": "cnr", "cnr": "GAHC010000000001"},
            headers=login(api, "edu_admin"),
        )
    assert r.status_code == 503 and r.json()["detail"]["code"] == "napix_off"
    assert count(world, "napix_call_log") == 0 and gw.seen == []
    assert audits(world, "case.search_court") == []


# ------------------------------------------------------------------------------------------------ by CNR


def test_cnr_local_hit_then_court_fetch(api, world, types):
    with world.Session() as s:
        held = make_case(s, cnr="GAHC010129772026", case_no="WP(C)/3600/2026")
        apply_dossier(s, held, sample("cnr_pending.json"))
        s.commit()
    headers = login(api, "edu_admin")
    r = api.post("/cases/search-court", json={"kind": "cnr", "cnr": "gahc010129772026"}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "local" and body["calls"] == 0 and body["created"] == 0
    assert (
        body["items"][0]["case"]["cnr"] == "GAHC010129772026"
        and body["items"][0]["dossier_status"] == "fetched"
    )
    assert body["items"][0]["match"] == "cnr" and body["items"][0]["visible"] is True  # a pool case
    assert api.gw.seen == []
    # a CNR not held: one call, a search-born case with its dossier and order PDFs queued
    r = api.post("/cases/search-court", json={"kind": "cnr", "cnr": "GAHC010000000777"}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "court" and body["calls"] == 1 and body["created"] == 1
    assert [c["path"] for c in api.gw.seen] == ["hc-cnr-api/CNR"]
    with world.Session() as s:
        case = s.scalar(sa.select(Case).where(Case.cnr == "GAHC010000000777"))
        assert case.first_seen_source == FirstSeenSource.SEARCH and case.last_full_refresh_at is not None
        assert not case.is_provisional and case.petitioner_summary == "PROSANJIT NUNISA AND 66 ORS"
        assert s.scalar(sa.select(sa.func.count()).where(CaseParty.case_id == case.id)) == 81
        queued = s.scalars(
            sa.select(FetchQueueItem).where(
                FetchQueueItem.kind == FetchKind.ORDER_PDF, FetchQueueItem.ref.like("GAHC010000000777|%")
            )
        ).all()
        assert len(queued) == 3
    rows = audits(world, "case.search_court")
    assert len(rows) == 2 and rows[0].after["outcome"] == "ok" and rows[0].after["calls"] == 0
    assert rows[1].after == {
        **rows[1].after,
        "kind": "cnr",
        "calls": 1,
        "results": 1,
        "created": 1,
        "outcome": "ok",
    }
    assert rows[1].actor_name == "Edu Admin" and rows[1].case_id == case.id
    assert count(world, "napix_call_log", "api = 'hc-cnr-api/CNR'") == 1
    assert count(world, "napix_responses", "api = 'hc-cnr-api/CNR'") == 1
    # a malformed CNR is refused by validation before anything happens
    assert (
        api.post("/cases/search-court", json={"kind": "cnr", "cnr": "nope"}, headers=headers).status_code
        == 422
    )


# ------------------------------------------------------------------------------------------------ by case number


def test_case_number_search_stores_the_row_and_fetches_the_exact_dossier(api, world, types):
    headers = login(api, "edu_admin")
    r = api.post(
        "/cases/search-court",
        json={"kind": "case_number", "case_type": "WA", "reg_no": 435, "reg_year": 2024},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert (
        body["source"] == "court" and body["calls"] == 2 and body["created"] == 1 and body["unmatched"] == []
    )
    assert [c["path"] for c in api.gw.seen] == ["hc-case-search-api/casesearch", "hc-cnr-api/CNR"]
    assert "case_type=112|reg_no=435|reg_year=2024" in api.gw.seen[0]["plain"]
    item = body["items"][0]
    assert item["case"]["cnr"] == WA_CNR and item["dossier_status"] == "fetched"
    with world.Session() as s:
        case = s.scalar(sa.select(Case).where(Case.cnr == WA_CNR))
        assert case.case_type_text == "WP(C)"  # the dossier (the sample) is authoritative over the search row
        assert case.reg_no == 3600 and case.last_full_refresh_at is not None
    # held with a dossier now → local, no call
    api.gw.seen.clear()
    r = api.post(
        "/cases/search-court",
        json={"kind": "case_number", "case_type": "111", "reg_no": 3600, "reg_year": 2026},
        headers=headers,
    )
    assert r.status_code == 200 and r.json()["source"] == "local" and api.gw.seen == []
    # an unknown case type → 400 and no call
    r = api.post(
        "/cases/search-court",
        json={"kind": "case_number", "case_type": "ZZZ", "reg_no": 1, "reg_year": 2024},
        headers=headers,
    )
    assert r.status_code == 400 and r.json()["detail"]["code"] == "bad_input" and api.gw.seen == []


# ------------------------------------------------------------------------------------------------ by party


def test_party_search_stores_rows_without_dossiers_and_scores_them(api, world, types):
    with world.Session() as s:
        s.add(OfficeKeyword(keyword="JANIFA", office_id=world.office(s, "EDU").id))
        s.commit()
    headers = login(api, "edu_admin")
    r = api.post(
        "/cases/search-court",
        json={"kind": "party", "name": "JANIFA", "reg_year": 2024},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "court" and body["calls"] == 1 and body["created"] == 3
    assert [c["path"] for c in api.gw.seen] == ["hc-party-name-api/partyname"]
    assert "pend_disp=P|litigant_name=JANIFA|reg_year=2024" in api.gw.seen[0]["plain"]
    assert {i["case"]["cnr"] for i in body["items"]} == PARTY_CNRS
    assert all(
        i["dossier_status"] == "not_fetched" and i["in_pool"] and i["claimable"] for i in body["items"]
    )
    with world.Session() as s:
        ia = s.scalar(sa.select(Case).where(Case.cnr == "GAHC010271682024"))
        assert ia.case_no_text == "I.A.(Civil)/3959/2024" and ia.case_type_text == "I.A.(Civil)"
        assert ia.petitioner_summary is None and ia.respondent_summary == "DR. JANIFA KAIFEE AHMED"
        assert ia.case_type_id is not None and ia.is_provisional and ia.last_full_refresh_at is None
        wa = s.scalar(sa.select(Case).where(Case.cnr == WA_CNR))
        assert wa.reg_no == 435 and wa.reg_year == 2024 and wa.first_seen_source == FirstSeenSource.SEARCH
        scores = s.scalars(sa.select(CaseOfficeScore).where(CaseOfficeScore.case_id == wa.id)).all()
        assert len(scores) == 1 and float(scores[0].score) == 0.4
        assert s.scalar(sa.select(sa.func.count()).select_from(CaseParty)) == 0  # no dossier fetched
        payload = s.execute(
            sa.text("select payload from napix_responses where api = 'hc-party-name-api/partyname'")
        ).scalar()
        assert payload["casenos"]["case3"]["type_name"] == "I.A.(Civil)"  # verbatim
    # found locally through the word search
    r = api.get("/cases/search?q=janifa", headers=headers)
    assert r.status_code == 200 and {i["case"]["cnr"] for i in r.json()["items"]} == PARTY_CNRS
    # pend_disp both → two calls, nothing created twice
    api.gw.seen.clear()
    r = api.post(
        "/cases/search-court",
        json={"kind": "party", "name": "JANIFA", "reg_year": 2024, "pend_disp": "both"},
        headers=headers,
    )
    assert r.status_code == 200 and r.json()["calls"] == 2 and r.json()["created"] == 0
    assert [c["plain"][-30:] for c in api.gw.seen] and len(api.gw.seen) == 2
    assert "pend_disp=P|" in api.gw.seen[0]["plain"] and "pend_disp=D|" in api.gw.seen[1]["plain"]
    assert count(world, "cases") == 3


def test_invalid_cino_is_unmatched_and_search_fields_never_overwrite_a_dossier(api, world, types):
    with world.Session() as s:
        held = make_case(s, cnr=WA_CNR, case_no="WP(C)/3600/2026")
        apply_dossier(s, held, {**sample("cnr_pending.json"), "cino": WA_CNR})
        s.commit()
    data = sample("party_name_2026-09-03.json")
    data["casenos"]["case1"]["cino"] = "NOT-A-CNR"
    api.gw.responses = [lambda p, q, r: api.gw.envelope(data)] + api.gw.responses
    headers = login(api, "edu_admin")
    r = api.post(
        "/cases/search-court", json={"kind": "party", "name": "JANIFA", "reg_year": 2024}, headers=headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 1 and len(body["items"]) == 2
    assert body["unmatched"] == [
        {
            "type_name": "WP(C)",
            "reg_no": "6434",
            "reg_year": "2024",
            "pet_name": "DR. JANIFA KAIFEE AHMED",
            "res_name": "THE STATE OF ASSAM AND 3 ORS.",
        }
    ]
    assert count(world, "cases", "cnr = 'NOT-A-CNR'") == 0 and count(world, "cases") == 2
    with world.Session() as s:
        wa = s.scalar(sa.select(Case).where(Case.cnr == WA_CNR))
        assert wa.petitioner_summary == "PROSANJIT NUNISA AND 66 ORS"  # the dossier's value stays
        assert wa.case_type_text == "WP(C)" and wa.reg_no == 3600


# ------------------------------------------------------------------------------------------------ the guard


def _call_log(world, *, remaining: int, hours_ago: float):
    with world.Session() as s:
        s.execute(
            sa.text(
                "insert into napix_call_log (api, params_sha256, ok, rate_limit_remaining, called_at) "
                "values ('hc-cnr-api/CNR', 'x', true, :rem, :at)"
            ),
            {"rem": remaining, "at": datetime.now(UTC) - timedelta(hours=hours_ago)},
        )
        s.commit()


def test_quota_floor_blocks_this_hour_only(api, world, types):
    headers = login(api, "edu_admin")
    _call_log(world, remaining=20, hours_ago=1.5)  # the previous clock hour never blocks
    r = api.post("/cases/search-court", json={"kind": "cnr", "cnr": "GAHC010000000001"}, headers=headers)
    assert r.status_code == 200, r.text
    minutes_into_hour = datetime.now(UTC).minute
    if minutes_into_hour == 0:
        pytest.skip("on the hour boundary the 'this hour' row cannot be placed reliably")
    _call_log(world, remaining=49, hours_ago=0.0)  # below the floor of 50, this clock hour
    r = api.post("/cases/search-court", json={"kind": "cnr", "cnr": "GAHC010000000002"}, headers=headers)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "napix_budget"
    assert 1 <= r.json()["detail"]["retry_after"] <= 3600 and r.headers["retry-after"]
    assert count(world, "cases", "cnr = 'GAHC010000000002'") == 0
    # the floor is a setting
    api.settings.napix_search_floor = 10
    r = api.post("/cases/search-court", json={"kind": "cnr", "cnr": "GAHC010000000002"}, headers=headers)
    assert r.status_code == 200


def test_per_user_hourly_limit(api, world, types):
    with world.Session() as s:
        actor, admin = world.actor(s, "edu_admin")
        for _ in range(30):
            write_audit(s, actor, "case.search_court", "napix_search", None, after={"outcome": "ok"})
        s.commit()
    headers = login(api, "edu_admin")
    r = api.post("/cases/search-court", json={"kind": "cnr", "cnr": "GAHC010000000003"}, headers=headers)
    assert r.status_code == 429 and r.json()["detail"]["code"] == "search_limit"
    assert 1 <= r.json()["detail"]["retry_after"] <= 3600
    assert len(audits(world, "case.search_court")) == 30  # the refused search writes nothing
    with world.Session() as s:
        c = make_case(s)
        s.commit()
        cid = c.id
    r = api.post(f"/cases/{cid}/fetch-court", headers=headers)
    assert r.status_code == 429
    # another user is not affected; the limit is a setting
    r = api.post(
        "/cases/search-court", json={"kind": "cnr", "cnr": "GAHC010000000003"}, headers=login(api, "edu_head")
    )
    assert r.status_code == 200
    api.settings.napix_search_per_user_hour = 100
    r = api.post("/cases/search-court", json={"kind": "cnr", "cnr": "GAHC010000000004"}, headers=headers)
    assert r.status_code == 200


def test_gateway_failure_is_recorded_and_audited(api, world, types):
    api.gw.responses = [lambda p, q, r: httpx.Response(500)] * 10 + api.gw.responses
    headers = login(api, "edu_admin")
    r = api.post("/cases/search-court", json={"kind": "cnr", "cnr": "GAHC010000000005"}, headers=headers)
    assert r.status_code == 502 and r.json()["detail"]["code"] == "napix_unavailable"
    # read back in a new session: the attempts and the audit row were committed before the error
    assert count(world, "napix_call_log", "api = 'hc-cnr-api/CNR' and ok = false") == 3
    rows = audits(world, "case.search_court")
    assert (
        len(rows) == 1
        and rows[0].after["outcome"] == "failed:napix_unavailable"
        and rows[0].after["calls"] == 3
    )
    # the typed CNR was never verified: no case row and no event were committed with it
    assert count(world, "cases", "cnr = 'GAHC010000000005'") == 0
    assert count(world, "events", "payload->>'cnr' = 'GAHC010000000005'") == 0


def test_timeout_answers_504(api, world, types, monkeypatch):
    import asyncio

    from aslms.integration.napix import hc as hc_module

    async def slow(self, cnr):
        await asyncio.sleep(0.5)
        return {}

    monkeypatch.setattr(hc_module.NapixHighCourt, "case_by_cnr", slow)
    api.settings.napix_search_timeout_seconds = 0.05
    r = api.post(
        "/cases/search-court",
        json={"kind": "cnr", "cnr": "GAHC010000000006"},
        headers=login(api, "edu_admin"),
    )
    assert r.status_code == 504 and r.json()["detail"]["code"] == "napix_timeout"
    assert audits(world, "case.search_court")[0].after["outcome"] == "failed:napix_timeout"
    assert count(world, "cases", "cnr = 'GAHC010000000006'") == 0


def test_cnr_the_court_does_not_know_leaves_no_case(api, world, types):
    """A well-formed CNR the court answers 628 for: 200 `not_found`, audited, and no `cases` row, no
    `case_created` event and no queue item carry the unverified identifier (never fabricate identifiers)."""
    api.gw.responses = [lambda p, q, r: api.gw.encrypted_status(628)] + api.gw.responses
    headers = login(api, "edu_admin")
    before = count(world, "cases")
    r = api.post("/cases/search-court", json={"kind": "cnr", "cnr": "GAHC019999999999"}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "court" and body["calls"] == 1 and body["created"] == 0 and body["items"] == []
    assert [c["path"] for c in api.gw.seen] == ["hc-cnr-api/CNR"]
    assert count(world, "cases") == before and count(world, "cases", "cnr = 'GAHC019999999999'") == 0
    assert count(world, "events", "payload->>'cnr' = 'GAHC019999999999'") == 0
    assert count(world, "fetch_queue", "ref like 'GAHC019999999999%'") == 0
    rows = audits(world, "case.search_court")
    assert len(rows) == 1 and rows[0].after["outcome"] == "not_found" and rows[0].after["calls"] == 1
    # the call itself is on record
    assert count(world, "napix_call_log", "api = 'hc-cnr-api/CNR'") == 1


def test_dossier_labelled_with_another_cnr_is_refused(api, world, types):
    """The court answering a dossier whose `cino` is not the asked CNR is a protocol fault: 502, no case."""
    api.gw.responses = [
        lambda p, q, r: api.gw.envelope({**sample("cnr_pending.json"), "cino": "GAHC010000000001"})
    ] + api.gw.responses
    r = api.post(
        "/cases/search-court",
        json={"kind": "cnr", "cnr": "GAHC010000000002"},
        headers=login(api, "edu_admin"),
    )
    assert r.status_code == 502, r.text
    assert count(world, "cases", "cnr in ('GAHC010000000001', 'GAHC010000000002')") == 0
    assert audits(world, "case.search_court")[0].after["outcome"] == "failed:napix_unavailable"


# ------------------------------------------------------------------------------------------------ fetch-court


def test_fetch_court_on_a_party_hit_then_409(api, world, types):
    headers = login(api, "edu_admin")
    r = api.post(
        "/cases/search-court", json={"kind": "party", "name": "JANIFA", "reg_year": 2024}, headers=headers
    )
    assert r.status_code == 200
    api.gw.seen.clear()
    r = api.post(f"/cases/{WA_CNR}/fetch-court", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["dossier_status"] == "fetched" and r.json()["case"]["cnr"] == WA_CNR
    assert [c["path"] for c in api.gw.seen] == ["hc-cnr-api/CNR"]
    rows = audits(world, "case.fetch_court")
    assert len(rows) == 1 and rows[0].after["outcome"] == "ok" and rows[0].after["calls"] == 1
    assert rows[0].entity_type == "case" and rows[0].case_id is not None
    r = api.post(f"/cases/{WA_CNR}/fetch-court", headers=headers)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "already_fetched"
    assert len(audits(world, "case.fetch_court")) == 1  # a refused fetch spends nothing and writes nothing


def test_fetch_court_resolves_a_provisional_case_by_number(api, world, types):
    with world.Session() as s:
        court = s.scalar(sa.select(Court).where(Court.est_code == "GAHC01"))
        prov = Case(
            court_id=court.id,
            case_no_text="WA/435/2024",
            case_type_text="WA",
            reg_no=435,
            reg_year=2024,
            ref_no="ASLMS/GOA/CASE/2025/900001",
            first_seen_source=FirstSeenSource.CAUSELIST,
            is_provisional=True,
        )
        s.add(prov)
        other = Case(
            court_id=court.id,
            case_no_text="WA/999/2024",
            case_type_text="WA",
            reg_no=999,
            reg_year=2024,
            ref_no="ASLMS/GOA/CASE/2025/900002",
            first_seen_source=FirstSeenSource.CAUSELIST,
            is_provisional=True,
        )
        s.add(other)
        s.commit()
        prov_id, other_id = prov.id, other.id
    headers = login(api, "edu_admin")
    r = api.post(f"/cases/{prov_id}/fetch-court", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["case"]["cnr"] == WA_CNR and r.json()["dossier_status"] == "fetched"
    assert [c["path"] for c in api.gw.seen] == ["hc-case-search-api/casesearch", "hc-cnr-api/CNR"]
    with world.Session() as s:
        case = s.get(Case, prov_id)
        assert case.cnr == WA_CNR and not case.is_provisional  # the CNR came from the court
    # a number the court does not know: 404, the case unchanged, the attempt audited
    api.gw.seen.clear()
    r = api.post(f"/cases/{other_id}/fetch-court", headers=headers)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "not_found_at_court"
    assert [c["path"] for c in api.gw.seen] == ["hc-case-search-api/casesearch"]
    with world.Session() as s:
        case = s.get(Case, other_id)
        assert case.cnr is None and case.is_provisional and case.last_full_refresh_at is None
    rows = audits(world, "case.fetch_court")
    assert [r.after["outcome"] for r in rows] == ["ok", "not_found"]
    # a directorate user holds no cases.search_court
    assert api.post(f"/cases/{other_id}/fetch-court", headers=login(api, "dse_user")).status_code == 403
    assert (
        api.post(
            "/cases/search-court", json={"kind": "cnr", "cnr": WA_CNR}, headers=login(api, "dse_user")
        ).status_code
        == 403
    )
    assert api.post("/cases/search-court", json={"kind": "cnr", "cnr": WA_CNR}).status_code == 401
    assert (
        api.post("/cases/00000000-0000-0000-0000-000000000000/fetch-court", headers=headers).status_code
        == 404
    )


def test_json_body_shapes_are_validated(api, world, types):
    headers = login(api, "edu_admin")
    for body in (
        {"kind": "party", "name": "ab", "reg_year": 2024},
        {"kind": "party", "name": "abc", "reg_year": 1900},
        {"kind": "party", "name": "abc", "reg_year": 2024, "pend_disp": "X"},
        {"kind": "party", "name": "ASSAM|est_code=XXHC01|reg_year=1999", "reg_year": 2024},
        {"kind": "party", "name": "ASSAM=1", "reg_year": 2024},
        {"kind": "party", "name": "ASSAM;drop", "reg_year": 2024},
        {"kind": "party", "name": "ASSAM\nX", "reg_year": 2024},
        {"kind": "case_number", "case_type": "WA", "reg_no": 0, "reg_year": 2024},
        {"kind": "advocate", "name": "abc", "reg_year": 2024},
        {"cnr": "GAHC010000000001"},
    ):
        r = api.post("/cases/search-court", json=body, headers=headers)
        assert r.status_code == 422, (body, r.text)
    assert api.gw.seen == [] and json.dumps(body)  # nothing reached the gateway


def test_party_name_cannot_alter_the_gateway_request(api, world, types):
    """Defence in depth below the schema: the service refuses a name with `|` or `=` and the NAPIX layer
    refuses to build a plain text from such a value, so no call is made from any entry point."""
    import asyncio

    from aslms.core.errors import NapixInputError
    from aslms.domain.courts import Court as CourtModel
    from aslms.services import court_search

    with world.Session() as s:
        court = s.scalar(sa.select(CourtModel).where(CourtModel.est_code == "GAHC01"))
        _, hc = api.app.state.napix_factory()
        with pytest.raises(court_search.CourtSearchError):
            asyncio.run(
                court_search._search_party(
                    s, hc, court, {"name": "ASSAM|est_code=XXHC01", "reg_year": 2024, "pend_disp": "P"}
                )
            )
        with pytest.raises(NapixInputError):
            asyncio.run(hc.search_party("ASSAM|est_code=XXHC01|reg_year=1999", 2024))
    assert api.gw.seen == []
    # names the court actually prints go through
    r = api.post(
        "/cases/search-court",
        json={"kind": "party", "name": "DR. JANIFA KAIFEE AHMED", "reg_year": 2024},
        headers=login(api, "edu_admin"),
    )
    assert r.status_code == 200, r.text
    r = api.post(
        "/cases/search-court",
        json={"kind": "party", "name": "M/S S.K. & CO. (INDIA), ORS.", "reg_year": 2024},
        headers=login(api, "edu_admin"),
    )
    assert r.status_code == 200, r.text
