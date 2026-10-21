"""The System health request console (design `system-health-inspector`): who may use it, reading never calls the
gateway, the pre-filled form and decision 6's visibility, Send with held and edited values (one call, audited with the
parameters sent, nothing applied), the shared guard, the last send and the latest stored answer, the full answer for
State-wide viewers, no secret anywhere, the Access token card and "Check token", and the NAPIX documents. The switch is
never set: `napix_configured` is patched as in `test_api_system_health.py`."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa

from aslms.domain.alerts import Alert
from aslms.domain.cases import Case, CaseAdvocate, CaseHearing, CaseParty
from aslms.domain.causelists import Causelist
from aslms.domain.documents import Document, Order
from aslms.domain.events import AuditLog, Event
from aslms.domain.ops import FetchQueueItem, NapixCallLog
from aslms.integration.napix.client import TokenCache, TokenRenewal
from aslms.integration.napix.crypto import NapixCrypto
from aslms.services.audit import write_audit
from tests.db import docs_support as ds

# ruff: noqa: F811 — the fixtures `gw`, `held` and `switch_on` are imported and requested by name
from tests.db.test_api_system_health import (  # noqa: F401
    ADVOCATE,
    CNR,
    KEYS,
    PARTY,
    _api_with,
    _calls,
    _count,
    _grant,
    _log,
    fake_probes,
    gw,
    held,
    switch_on,
)
from tests.redis_stub import RedisStub
from tests.unit.conftest import KEY

PDFS = Path(__file__).resolve().parents[3] / "docs" / "specs" / "pdf"
OTHER_CNR = "GAHC010118832025"  # from the Search by Filing Number sample (docs/specs/samples), not held
SECRETS = {
    "napix_client_id": "client-id-zq81",
    "napix_client_secret": "client-secret-zq82",
    "napix_dept_id": "dept-id-zq83",
    "napix_auth_key": "auth-key-zq84xxx",
    "aslms_app_password": "app-password-zq85",
    "aslms_readonly_password": "readonly-password-zq86",
    "postgres_password": "postgres-password-zq87",
    "redis_password": "redis-password-zq88",
    "mailtrap_api_token": "mailtrap-token-zq89",
    "smtp_password": "smtp-password-zq90",
    "sourcetrace_api_key": "sourcetrace-key-zq91",
}
BASE = "/admin/system-health"


@pytest.fixture()
def api(world, tmp_path):
    """The app with the NAPIX documents mounted, distinctive values in every secret setting and a dict-backed Redis
    behind the token cache."""
    client = ds.make_api(world, tmp_path, napix_docs_dir=str(PDFS), **SECRETS)
    client.app.state.service_probes = fake_probes()
    client.redis = RedisStub()
    client.app.state.napix_token_cache = TokenCache(redis_client=client.redis)
    yield client
    client.__exit__(None, None, None)


def _console(api, key: str, h: dict) -> dict:
    r = api.get(f"{BASE}/napix/{key}/console", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _send(api, key: str, h: dict, values: dict | None = None):
    if values is None:
        return api.post(f"{BASE}/napix/{key}/test", headers=h)
    return api.post(f"{BASE}/napix/{key}/test", headers=h, json={"values": values})


def _form(console: dict) -> dict:
    return {f["name"]: f["value"] for f in console["fields"]}


def _audits(world, action: str = "napix.api_tested") -> list[AuditLog]:
    with world.Session() as s:
        return list(
            s.scalars(
                sa.select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.created_at)
            ).all()
        )


def _age_audits(world, minutes: int = 2) -> None:
    """Moves every audit row back in time (the per-API interval); audit_log is append-only."""
    with world.Session() as s:
        s.execute(sa.text("SET session_replication_role = replica"))
        s.execute(sa.text(f"UPDATE audit_log SET created_at = created_at - interval '{minutes} minutes'"))
        s.commit()


ENDPOINTS = (
    ("GET", f"{BASE}/napix/cnr/console", None),
    ("POST", f"{BASE}/napix/state/preview", {"values": {}}),
    ("GET", f"{BASE}/napix/state/response?source=latest", None),
    ("GET", f"{BASE}/napix/cnr/reference", None),
    ("GET", f"{BASE}/napix/token/reference", None),
    ("POST", f"{BASE}/napix/state/postman", {"values": {}}),
    ("GET", f"{BASE}/docs", None),
    ("GET", f"{BASE}/docs/hc_spec", None),
    ("GET", f"{BASE}/token", None),
    ("POST", f"{BASE}/token/check", None),
)
# with the switch off and nothing stored: the answers a holder gets
HOLDER = {
    f"{BASE}/napix/state/response?source=latest": 404,  # no stored answer yet
    f"{BASE}/token/check": 409,  # napix_off
}


# ------------------------------------------------------------------------------------------------ who


def test_every_new_endpoint_needs_admin_service_health(api, world, gw):
    for key in ("edu_off1", "central_op", "oversight", "edu_auditor"):
        h = ds.login(api, key)
        for method, path, body in ENDPOINTS:
            r = api.request(method, path, headers=h, json=body)
            assert r.status_code == 403, (key, path, r.text)
    root = ds.login(api, "root")
    for method, path, body in ENDPOINTS:
        r = api.request(method, path, headers=root, json=body)
        assert r.status_code == HOLDER.get(path, 200), (path, r.text)
    _grant(world, "edu_off1")
    h = ds.login(api, "edu_off1")
    for method, path, body in ENDPOINTS:
        r = api.request(method, path, headers=h, json=body)
        expected = 403 if "/response" in path else HOLDER.get(path, 200)  # no cases.view_all
        assert r.status_code == expected, (path, r.text)
    assert gw.seen == [] and gw.token_calls == 0


def test_reading_never_calls_the_gateway(api, world, gw, held, switch_on):
    h = ds.login(api, "root")
    before = _count(world, NapixCallLog), _count(world, AuditLog)
    assert api.get(BASE, headers=h).status_code == 200
    for key in KEYS:
        c = _console(api, key, h)
        assert c["api"] == key and c["send"]["available"] is True, (key, c["send"])
        form = _form(c)
        assert api.post(f"{BASE}/napix/{key}/preview", headers=h, json={"values": form}).status_code == 200, (
            key
        )
        assert api.get(f"{BASE}/napix/{key}/reference", headers=h).status_code == 200
        r = api.post(f"{BASE}/napix/{key}/postman", headers=h, json={"values": form})
        assert r.status_code == 200 and r.headers["content-disposition"].startswith("attachment"), key
    assert api.get(f"{BASE}/docs", headers=h).status_code == 200
    assert api.get(f"{BASE}/token", headers=h).status_code == 200
    assert gw.seen == [] and gw.token_calls == 0
    assert (_count(world, NapixCallLog), _count(world, AuditLog)) == before
    assert api.redis.data == {}  # no token metadata either


# ------------------------------------------------------------------------------------------------ the form


def test_console_prefills_the_held_sample_with_masked_dept_id(api, world, gw, held):
    c = _console(api, "cnr", ds.login(api, "root"))
    assert c["method"] == "GET" and c["url"] == "https://delhigw.napix.gov.in/nic/ecourts/hc-cnr-api/CNR"
    (field,) = c["fields"]
    assert field == field | {
        "name": "cino",
        "value": CNR,
        "prefilled": True,
        "source": "held",
        "mandatory": True,
    }
    assert c["plain"] == f"cino={CNR}" and c["plain_complete"] is True
    env = {e["name"]: e for e in c["envelope"]}
    assert env["dept_id"]["shown"] == "de…" and "masked" in env["dept_id"]["note"]
    assert env["request_str"]["shown"] == "encrypted, 44 characters, not shown"
    assert env["request_token"]["shown"] == NapixCrypto("any").token(f"cino={CNR}") == c["request_token"]
    assert env["version"]["shown"] == "v1.0"
    assert [h["shown"] for h in c["headers"]] == [
        "Bearer ‹access token, not shown›",
        "application/json, application/pdf",
    ]
    assert c["doc"] == {"doc": "hc_spec", "page": 12, "section": "6.1 Search by CNR API", "available": True}
    assert c["send"]["available"] is False and "switched off" in c["send"]["reason"]  # the switch is off
    assert c["last_send"] is None and c["latest_answer"] is None and c["full_answer_allowed"] is True
    assert "<ACCESS_TOKEN>" in c["templates"]["curl"]
    status = _console(api, "current_status", ds.login(api, "root"))
    assert status["method"] == "POST" and "query string" in status["method_note"]
    assert "no input" in _console(api, "state", ds.login(api, "root"))["no_input_note"]
    sources = {f["name"]: f["source"] for f in _console(api, "case_search", ds.login(api, "root"))["fields"]}
    assert sources == {"est_code": "settings", "case_type": "held", "reg_no": "held", "reg_year": "held"}


def test_console_leaves_names_and_case_keys_of_invisible_cases_empty(api, world, gw, held, switch_on):
    _grant(world, "health_admin")  # Health cannot see the case Education claimed
    h = ds.login(api, "health_admin")
    party = _console(api, "party_name", h)
    form = {f["name"]: f for f in party["fields"]}
    assert form["litigant_name"]["value"] == "" and form["litigant_name"]["prefilled"] is False
    assert "cannot see" in form["litigant_name"]["hint"]
    assert "litigant_name=‹type a name›" in party["plain"] and party["plain_complete"] is False
    assert (
        party["request_token"] is None and party["send"]["available"] is True
    )  # the form decides completeness
    assert PARTY not in json.dumps(party)
    cnr = _console(api, "cnr", h)
    assert cnr["fields"][0]["value"] == "" and "cino=‹type a CNR›" == cnr["plain"]
    assert CNR not in json.dumps(cnr)
    search = {f["name"]: f["value"] for f in _console(api, "case_search", h)["fields"]}
    assert search["reg_no"] == "" and search["case_type"] == "111" and search["reg_year"] == "2024"
    adv = _console(api, "advocate_name", h)
    assert ADVOCATE not in json.dumps(adv)
    # a send of the typed value is fine; a send of the empty form is refused before any call
    r = _send(api, "party_name", h, {**_form(party), "litigant_name": ""})
    assert r.status_code == 422 and r.json()["detail"]["errors"] == {"litigant_name": "Required"}
    assert gw.seen == []


def test_console_prefills_names_of_visible_cases(api, world, gw, held):
    _grant(world, "edu_admin")
    h = ds.login(api, "edu_admin")
    party = _console(api, "party_name", h)
    assert _form(party)["litigant_name"] == PARTY and party["plain_complete"] is True
    assert party["plain"] == f"est_code=GAHC01|pend_disp=P|litigant_name={PARTY}|reg_year=2024"
    assert _form(_console(api, "advocate_name", h))["advocate_name"] == ADVOCATE
    assert _form(_console(api, "cnr", h))["cino"] == CNR


def test_send_without_body_never_uses_a_sample_hidden_from_the_caller(api, world, gw, held, switch_on):
    """Decision 6: every value sent was seen or typed by the sender. A send with no body whose held sample carries a
    name, CNR, case or filing number of a case the caller cannot see is refused before any call, writing nothing."""
    _grant(world, "health_admin")  # Health cannot see the case Education claimed
    h = ds.login(api, "health_admin")
    for key in ("party_name", "advocate_name", "cnr", "case_search", "filing", "current_status"):
        r = _send(api, key, h)
        assert r.status_code == 409, (key, r.text)
        assert r.json()["detail"]["code"] == "sample_hidden"
        assert PARTY not in r.text and CNR not in r.text and ADVOCATE not in r.text
    assert gw.seen == [] and _audits(world) == [] and _calls(world) == []
    # nothing hidden in a master's sample: a send with no body still runs
    assert _send(api, "state", h).status_code == 200
    # the Education administrator sees the case: the held name is sent and shown to them
    _grant(world, "edu_admin")
    r = _send(api, "party_name", ds.login(api, "edu_admin"))
    assert r.status_code == 200, r.text
    assert f"litigant_name={PARTY}" in r.json()["request"]["plain"]


def test_last_send_shows_case_values_only_to_viewers_who_may_see_them(api, world, gw, held, switch_on):
    """The Visibility paragraph: a past send's name, CNR, case or filing number is shown to the sender, to a holder
    of `cases.view_all` and, for a held sample, to a viewer who can see its case; otherwise it reads ‹not shown› and
    its hash is withheld."""
    _grant(world, "health_admin")
    _grant(world, "edu_admin")
    hh, he, hr = ds.login(api, "health_admin"), ds.login(api, "edu_admin"), ds.login(api, "root")
    assert _send(api, "cnr", hr).status_code == 200  # root sends the held CNR of Education's case
    hidden = _console(api, "cnr", hh)
    assert hidden["full_answer_allowed"] is False
    last = hidden["last_send"]
    assert last["plain"] == "cino=‹not shown›" and last["params_sha256"] is None and last["by"] == "person"
    assert CNR not in json.dumps(hidden)
    edu = _console(api, "cnr", he)
    assert edu["full_answer_allowed"] is False  # sees the case, not every case
    assert edu["last_send"]["plain"] == f"cino={CNR}" and edu["last_send"]["params_sha256"]
    assert _console(api, "cnr", hr)["last_send"]["plain"] == f"cino={CNR}"
    # a name typed by root: only root (the sender, and a holder of cases.view_all) sees it
    typed = "RAMESH CHANDRA BORAH"
    values = {**_form(_console(api, "party_name", hr)), "litigant_name": typed}
    r = _send(api, "party_name", hr, values)
    assert r.status_code == 200 and r.json()["edited"] is True
    for h in (hh, he):
        c = _console(api, "party_name", h)
        assert (
            "litigant_name=‹not shown›" in c["last_send"]["plain"]
            and "reg_year=2024" in c["last_send"]["plain"]
        )
        assert typed not in json.dumps(c) and c["last_send"]["params_sha256"] is None
    assert f"litigant_name={typed}" in _console(api, "party_name", hr)["last_send"]["plain"]
    # the sender always sees their own send
    assert _send(api, "advocate_name", he).status_code == 200
    assert ADVOCATE in _console(api, "advocate_name", he)["last_send"]["plain"]
    assert ADVOCATE not in json.dumps(_console(api, "advocate_name", hh))


def test_preview_rebuilds_the_plain_string_and_reports_field_errors(api, world, gw, held):
    h = ds.login(api, "root")
    r = api.post(f"{BASE}/napix/cnr/preview", headers=h, json={"values": {"cino": OTHER_CNR.lower()}})
    assert r.status_code == 200 and r.json()["plain"] == f"cino={OTHER_CNR}"
    assert r.json()["request_token"] == NapixCrypto("x").token(f"cino={OTHER_CNR}")
    bad = api.post(f"{BASE}/napix/cnr/preview", headers=h, json={"values": {"cino": "GAHC01"}})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "invalid_input"
    assert "cino" in bad.json()["detail"]["errors"]
    assert api.get(f"{BASE}/napix/cnr_alt/console", headers=h).status_code == 404


# ------------------------------------------------------------------------------------------------ Send


def test_send_with_held_values_is_one_call(api, world, gw, held, switch_on):
    h = ds.login(api, "root")
    form = _form(_console(api, "cnr", h))
    r = _send(api, "cnr", h, form)
    assert r.status_code == 200, r.text
    body = r.json()
    assert [(x["path"], x["plain"]) for x in gw.seen] == [("hc-cnr-api/CNR", f"cino={CNR}")]
    assert body["edited"] is False and body["ok"] is True and body["request"]["plain"] == f"cino={CNR}"
    assert body["structure"]["total"] > 10 and body["response_available"] is True
    (audit,) = _audits(world)
    assert audit.after["edited"] is False and audit.after["sample"]["case_ref_no"] == held["ref_no"]


def test_send_with_edited_values_is_one_call_with_those_values(api, world, gw, held, switch_on):
    h = ds.login(api, "root")
    r = _send(api, "cnr", h, {"cino": OTHER_CNR.lower()})
    assert r.status_code == 200, r.text
    assert [x["plain"] for x in gw.seen] == [f"cino={OTHER_CNR}"]  # the gateway decrypted the edited string
    body = r.json()
    assert body["edited"] is True and body["input"]["label"] == "The values in the form"
    (audit,) = _audits(world)
    assert audit.after["params"] == {"cino": OTHER_CNR} and audit.after["edited"] is True
    assert "case_ref_no" not in audit.after["sample"]
    # an edited court code reaches the same method
    r = _send(api, "case_type", h, {"est_code": "gahc01"})
    assert r.status_code == 200 and gw.seen[-1]["plain"] == "est_code=GAHC01"


def test_send_audit_row_holds_the_parameters_sent_and_the_new_facts(api, world, gw, held, switch_on):
    gw.rate_headers = {"X-RateLimit-Limit": "name=default,1000;", "X-RateLimit-Remaining": "870"}
    h = ds.login(api, "root")
    body = _send(
        api,
        "case_search",
        h,
        {"est_code": "GAHC01", "case_type": "111", "reg_no": "7714", "reg_year": "2024"},
    ).json()
    (audit,) = _audits(world)
    after = audit.after
    assert after["params"] == {"est_code": "GAHC01", "case_type": "111", "reg_no": "7714", "reg_year": "2024"}
    import hashlib

    plain = "est_code=GAHC01|case_type=111|reg_no=7714|reg_year=2024"
    assert after["params_sha256"] == hashlib.sha256(plain.encode()).hexdigest()
    assert after["edited"] is False  # the same values as the held sample
    assert after["rate_limit"] == {"limit": 1000, "remaining": 870} == body["rate_limit"]
    assert after["token_verified"] is True and after["response_id"] == body["response_id"]
    assert {p["path"] for p in after["structure"]["paths"]} >= {"casenos[].cino", "establishment_name"}
    assert body["inventory_diff"] == {"checked": True, "new": [], "absent": body["inventory_diff"]["absent"]}
    with world.Session() as s:
        assert (
            s.scalar(
                sa.text("SELECT count(*) FROM napix_responses WHERE id = :i"), {"i": body["response_id"]}
            )
            == 1
        )


def test_same_plain_as_form(api, world, gw, held, switch_on):
    h = ds.login(api, "root")
    assert _send(api, "cnr", h).status_code == 200  # no body: the held sample (row 109)
    c = _console(api, "cnr", h)
    last = c["last_send"]
    assert last["by"] == "you" and last["recorded"] is True and last["plain"] == f"cino={CNR}"
    assert last["same_plain_as_form"] is True and last["response_available"] is True
    assert last["http_meaning"].startswith("Everything is normal")
    edited = api.post(f"{BASE}/napix/cnr/preview", headers=h, json={"values": {"cino": OTHER_CNR}}).json()
    assert edited["plain_sha256"] != last["params_sha256"]
    _grant(world, "central_op")
    other = _console(api, "cnr", ds.login(api, "central_op"))["last_send"]
    assert other["by"] == "person"


def test_pre_item_audit_rows_read_not_recorded(api, world, gw, held):
    with world.Session() as s:
        actor, _ = world.actor(s, "root")
        write_audit(
            s, actor, "napix.api_tested", "napix", None,
            after={"api": "state", "path": "hc-state-api/state", "ok": True, "answered": True, "attempts": 1,
                   "duration_ms": 300, "http_status": 200, "napix_status": None, "error_family": None,
                   "remaining": 500, "sample": {}, "summary": {"kind": "rows", "row_count": 25, "field_names": [],
                                                               "facts": []}},
        )  # fmt: skip
        s.commit()
    last = _console(api, "state", ds.login(api, "root"))["last_send"]
    assert last["recorded"] is False and last["plain"] is None and last["edited"] is None
    assert last["rate_limit"] is None and last["structure"] is None and last["token_verified"] is None
    assert last["ok"] is True and last["summary"]["row_count"] == 25


def test_send_invalid_input_makes_no_call_and_writes_nothing(api, world, gw, held, switch_on):
    h = ds.login(api, "root")
    before = _count(world, NapixCallLog), _count(world, AuditLog)
    for values, field in (
        ({"cino": "NOT-A-CNR"}, "cino"),
        ({"cino": f"{CNR},{CNR}"}, "cino"),
        ({}, "cino"),
        ({"cino": CNR, "dept_id": "x"}, "dept_id"),
    ):
        r = _send(api, "cnr", h, values)
        assert r.status_code == 422 and field in r.json()["detail"]["errors"], (values, r.text)
    r = _send(api, "order", h, {"cino": CNR, "order_no": "1", "order_date": "2099-01-01"})
    assert r.status_code == 422 and "order_date" in r.json()["detail"]["errors"]
    assert gw.seen == [] and (_count(world, NapixCallLog), _count(world, AuditLog)) == before


def test_switch_off_refuses_an_edited_send_first(api, world, gw, held):
    r = _send(api, "cnr", ds.login(api, "root"), {"cino": "bad"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "napix_off"


def test_edited_case_type_and_est_code_must_be_held(api, world, gw, held, switch_on):
    h = ds.login(api, "root")
    base = {"est_code": "GAHC01", "case_type": "111", "reg_no": "7714", "reg_year": "2024"}
    r = _send(api, "case_search", h, {**base, "est_code": "GAHC09"})
    assert r.status_code == 422 and "est_code" in r.json()["detail"]["errors"]
    r = _send(api, "case_search", h, {**base, "case_type": "999"})
    assert r.status_code == 422 and r.json()["detail"]["errors"] == {
        "case_type": "Not a case type ASLMS holds for GAHC01"
    }
    r = _send(api, "district", h, {"state_code": "99"})
    assert r.status_code == 422 and "state_code" in r.json()["detail"]["errors"]
    assert gw.seen == []


def test_send_writes_no_case_data(api, world, gw, held, switch_on):
    tables = (
        Case,
        CaseParty,
        CaseAdvocate,
        CaseHearing,
        Order,
        Document,
        Causelist,
        FetchQueueItem,
        Event,
        Alert,
    )
    before = {m.__name__: _count(world, m) for m in tables}
    with world.Session() as s:
        responses = s.scalar(sa.text("SELECT count(*) FROM napix_responses"))
    h = ds.login(api, "root")
    r = _send(api, "cnr", h, {"cino": OTHER_CNR})  # a CNR ASLMS does not hold
    assert r.status_code == 200 and r.json()["ok"] is True
    assert {m.__name__: _count(world, m) for m in tables} == before
    with world.Session() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(Case).where(Case.cnr == OTHER_CNR)) == 0
        assert s.scalar(sa.text("SELECT count(*) FROM napix_responses")) == responses + 1
    c = _console(api, "cnr", h)
    assert c["not_saved_note"] == "Shown, not saved to cases. Use Search to add a case."


def test_edited_and_held_sends_share_the_interval_and_the_hourly_cap(world, tmp_path, held_world, switch_on):
    api, gateway = _api_with(world, tmp_path, health_test_per_user_hour=2)
    try:
        h = ds.login(api, "root")
        assert _send(api, "state", h).status_code == 200
        r = _send(api, "state", h, {})  # an (unedited) form send of the same API: the per-API interval
        assert r.status_code == 429 and r.json()["detail"]["code"] == "test_too_soon"
        assert _send(api, "cnr", h, {"cino": OTHER_CNR}).status_code == 200
        r = _send(api, "district", h, {"state_code": "18"})
        assert r.status_code == 429 and r.json()["detail"]["code"] == "test_limit"
        assert len(gateway.seen) == 2
    finally:
        api.__exit__(None, None, None)


@pytest.fixture()
def held_world(world, api, held):
    """The held data, built through this module's app (the `_api_with` app shares the world's database)."""
    return held


def test_latest_answer_structure_without_a_send(api, world, gw, held):
    data = json.loads(
        (PDFS.parents[1] / "specs" / "samples" / "state_master_2026-09-03.json").read_text("utf-8")
    )
    with world.Session() as s:
        _log(s, "hc-state-api/state", 5)  # params_sha256 "0" * 64
        s.execute(
            sa.text(
                "INSERT INTO napix_responses (api, params_sha256, params, payload_sha256, payload) "
                "VALUES ('hc-state-api/state', :ps, '{}', :sha, CAST(:p AS jsonb))"
            ),
            {"ps": "0" * 64, "sha": "1" * 64, "p": json.dumps(data)},
        )
        s.commit()
    c = _console(api, "state", ds.login(api, "root"))
    latest = c["latest_answer"]
    assert c["last_send"] is None and latest["by"] == "background" and latest["response_available"] is True
    assert {p["path"] for p in latest["structure"]["paths"]} == {"state[].state_code", "state[].state_name"}
    assert latest["inventory_diff"]["new"] == []
    assert "Bombay" not in json.dumps(c)  # the structure holds no value


# ------------------------------------------------------------------------------------------------ the full answer


def test_full_answer_needs_view_all_and_is_audited(api, world, gw, held, switch_on):
    h = ds.login(api, "root")
    body = _send(api, "cnr", h).json()
    rid = body["response_id"]
    r = api.get(f"{BASE}/napix/cnr/response", headers=h, params={"source": "send", "response_id": rid})
    assert r.status_code == 200, r.text
    full = r.json()
    assert full["payload"]["cino"] == CNR and full["source"] == "send" and full["bytes"] > 1000
    (view,) = _audits(world, "napix.response_viewed")
    assert view.after == {"api": "cnr", "response_id": rid, "source": "send", "bytes": full["bytes"]}
    assert view.entity_type == "napix"
    latest = api.get(f"{BASE}/napix/cnr/response", headers=h, params={"source": "latest"})
    assert latest.status_code == 200 and latest.json()["response_id"] == rid
    assert len(_audits(world, "napix.response_viewed")) == 2
    _grant(world, "health_admin")
    hh = ds.login(api, "health_admin")
    c = _console(api, "cnr", hh)
    assert c["full_answer_allowed"] is False and "every case" in c["full_answer_note"]
    denied = api.get(f"{BASE}/napix/cnr/response", headers=hh, params={"source": "send", "response_id": rid})
    assert denied.status_code == 403 and len(_audits(world, "napix.response_viewed")) == 2
    wrong_api = api.get(
        f"{BASE}/napix/state/response", headers=h, params={"source": "send", "response_id": rid}
    )
    assert wrong_api.status_code == 404 and wrong_api.json()["detail"]["code"] == "no_response"


def test_full_answer_too_large_is_413(world, tmp_path, held_world, switch_on):
    api, _gateway = _api_with(world, tmp_path, health_raw_max_bytes=10_000)
    try:
        h = ds.login(api, "root")
        body = _send(api, "act", h).json()  # the act master: about 600 KB
        assert body["ok"] is True and body["structure"]["paths"]
        r = api.get(
            f"{BASE}/napix/act/response",
            headers=h,
            params={"source": "send", "response_id": body["response_id"]},
        )
        assert r.status_code == 413 and r.json()["detail"]["code"] == "too_large"
        with world.Session() as s:
            n = s.scalar(
                sa.select(sa.func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "napix.response_viewed")
            )
        assert n == 0
    finally:
        api.__exit__(None, None, None)


# ------------------------------------------------------------------------------------------------ no secret


def test_no_secret_in_any_response(api, world, gw, held, switch_on, caplog, capsys):
    caplog.set_level(logging.DEBUG)
    # production's logging setup (core/logging.py) keeps httpx's request-URL lines out of the log
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    h = ds.login(api, "root")
    texts: list[str] = [api.get(BASE, headers=h).text]
    for key in ("cnr", "party_name", "state", "current_status"):
        c = api.get(f"{BASE}/napix/{key}/console", headers=h)
        form = _form(c.json())
        texts += [
            c.text,
            api.post(f"{BASE}/napix/{key}/preview", headers=h, json={"values": form}).text,
            api.post(f"{BASE}/napix/{key}/postman", headers=h, json={"values": form}).text,
            api.get(f"{BASE}/napix/{key}/reference", headers=h).text,
        ]
    sends = [
        _send(api, "cnr", h),
        _send(
            api,
            "party_name",
            h,
            {"est_code": "GAHC01", "pend_disp": "P", "litigant_name": "ANIL BORA", "reg_year": "2024"},
        ),
    ]
    texts += [r.text for r in sends]
    rid = sends[0].json()["response_id"]
    texts.append(
        api.get(f"{BASE}/napix/cnr/response", headers=h, params={"source": "send", "response_id": rid}).text
    )
    texts.append(api.post(f"{BASE}/token/check", headers=h).text)
    texts += [api.get(f"{BASE}/token", headers=h).text, api.get(f"{BASE}/docs", headers=h).text]
    texts.append(api.get(f"{BASE}/napix/token/reference", headers=h).text)
    with world.Session() as s:
        audits = [
            json.dumps(a.after)
            for a in s.scalars(sa.select(AuditLog).where(AuditLog.action.like("napix.%"))).all()
        ]
    assert len(audits) >= 4
    logs = "\n".join(r.getMessage() for r in caplog.records) + capsys.readouterr().out
    crypto = NapixCrypto(KEY)  # the gateway's key: the request_str actually sent
    ciphertexts = [crypto.encrypt(x["plain"]) for x in gw.seen]
    forbidden = list(SECRETS.values()) + ["tok1", "tok2", "tok3", "secret-test", "key-test", KEY, "dept-test"]
    forbidden += ciphertexts
    for where, blobs in (
        ("responses", texts),
        ("audit", audits),
        ("redis metadata", [repr({k: v for k, v in api.redis.data.items() if k != "napix:token"})]),
        ("log", [logs]),
    ):
        for secret in forbidden:
            assert not [b for b in blobs if secret in b], (where, secret)
    assert gw.token_calls >= 1 and len(gw.seen) == 2


# ------------------------------------------------------------------------------------------------ the token


def _token(api, h) -> dict:
    r = api.get(f"{BASE}/token", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _issued(api, minutes_ago: float = 10, ok: bool = True, family: str | None = None) -> None:
    cache = TokenCache(redis_client=api.redis)
    when = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    cache.note_request(
        TokenRenewal(ok=ok, http_status=200 if ok else 401, error_family=family, duration_ms=120,
                     expires_in=3600 if ok else None, token_type="Bearer" if ok else None,
                     scope="napix" if ok else None),
        now=when,
    )  # fmt: skip


def test_token_card_states(api, world, gw, switch_on, monkeypatch):
    h = ds.login(api, "root")
    # nothing held, nothing recorded, switch on: not known yet
    t = _token(api, h)
    assert t["status"] == "unknown" and t["held"] is False and t["shared_store"] is True
    assert t["endpoint"]["url"] == "https://delhigw.napix.gov.in/nic/ecourts//oauth2/token"
    assert "<CLIENT_KEY>:<CLIENT_SECRET>" in t["curl_token"] and t["check"]["allowed"] is True
    # held, not used yet
    _issued(api, 10)
    api.redis.set("napix:token", "tok-held", ex=3000)
    t = _token(api, h)
    assert (
        t["status"] == "ok" and t["held"] and 2990 <= t["ttl_seconds"] <= 3000 and t["accepted_since"] is None
    )
    assert t["obtained_at"] and t["expires_at"] and t["token_type"] == "Bearer" and t["scope"] == "napix"
    assert t["last_request"]["outcome"] == "obtained" and t["requests_today"] >= 1
    # held and accepted since issue
    with world.Session() as s:
        _log(s, "hc-cnr-api/CNR", 5, http=200)
        _log(s, "hc-state-api/state", 20, http=200)  # before the issue: not counted
        s.commit()
    t = _token(api, h)
    assert t["status"] == "ok" and t["accepted_since"]["api_label"] == "Case details by CNR"
    assert t["accepted_since"]["http_status"] == 200 and t["rejected_since"] == 0
    # 401 answers since issue with no renewal after them
    with world.Session() as s:
        _log(s, "hc-cnr-api/CNR", 2, ok=False, http=401)
        s.commit()
    t = _token(api, h)
    assert t["status"] == "down" and t["rejected_since"] == 1
    # a renewal after them: the 401 rows are before the new issue
    _issued(api, 1)
    assert _token(api, h)["status"] == "ok"
    # the last request failed while a token is still held
    _issued(api, 0.5, ok=False, family="NapixAuthError")
    t = _token(api, h)
    assert t["status"] == "warn" and t["last_failure"]["family"] == "NapixAuthError"
    assert t["last_request"]["outcome"] == "refused: check NAPIX_CLIENT_ID / SECRET"
    # ... and none held
    api.redis.delete("napix:token")
    assert _token(api, h)["status"] == "down"
    assert "tok-held" not in json.dumps(_token(api, h))
    # no shared store
    api.app.state.napix_token_cache = TokenCache()
    assert _token(api, h)["status"] in ("warn", "unknown")
    t = _token(api, h)
    assert t["shared_store"] is False
    # the switch off and nothing held
    monkeypatch.undo()
    api.app.state.napix_token_cache = TokenCache(redis_client=RedisStub())
    t = _token(api, h)
    assert t["status"] == "unknown" and t["napix_enabled"] is False
    assert gw.token_calls == 0 and gw.seen == []


def test_no_shared_store_with_a_held_token_is_warn(api, world, gw, switch_on):
    cache = TokenCache()
    cache.set("tok-local", 3000)
    api.app.state.napix_token_cache = cache
    t = _token(api, ds.login(api, "root"))
    assert t["status"] == "warn" and t["held"] is True and t["shared_store"] is False


def test_token_check_refusals_write_nothing(api, world, gw, held, engine, monkeypatch):
    h = ds.login(api, "root")

    def nothing_written():
        assert gw.token_calls == 0 and _audits(world, "napix.token_checked") == [] and api.redis.data == {}

    r = api.post(f"{BASE}/token/check", headers=h)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "napix_off"
    nothing_written()
    from aslms.core.config import Settings

    monkeypatch.setattr(Settings, "napix_configured", property(lambda self: True))
    # one check at a time
    with engine.connect() as conn, conn.begin():
        conn.execute(sa.text("SELECT pg_advisory_xact_lock(hashtextextended('napix-token-check', 0))"))
        r = api.post(f"{BASE}/token/check", headers=h)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "check_running"
    nothing_written()
    # the quota floor
    with world.Session() as s:
        _log(s, "hc-cnr-api/CNR", 0.2, remaining=10)
        s.commit()
    r = api.post(f"{BASE}/token/check", headers=h)
    assert r.status_code == 429 and r.json()["detail"]["code"] == "napix_budget"
    nothing_written()
    with world.Session() as s:
        s.execute(sa.text("SET session_replication_role = replica"))
        s.execute(sa.text("DELETE FROM napix_call_log"))
        s.commit()
    # the hourly cap shared with sends
    with world.Session() as s:
        actor, _ = world.actor(s, "root")
        for _ in range(30):
            write_audit(s, actor, "napix.api_tested", "napix", None, after={"api": "act", "ok": True})
        s.commit()
    r = api.post(f"{BASE}/token/check", headers=h)
    assert r.status_code == 429 and r.json()["detail"]["code"] == "test_limit"
    assert int(r.headers["Retry-After"]) > 0
    nothing_written()
    # a check by anyone within the interval
    _age_audits(world, 120)
    with world.Session() as s:
        actor, _ = world.actor(s, "central_op")
        write_audit(s, actor, "napix.token_checked", "napix", None, after={"ok": True})
        s.commit()
    r = api.post(f"{BASE}/token/check", headers=h)
    assert r.status_code == 429 and r.json()["detail"]["code"] == "check_too_soon"
    assert 500 < int(r.headers["Retry-After"]) <= 600
    assert gw.token_calls == 0 and api.redis.data == {}
    assert _token(api, h)["check"]["allowed"] is False


def test_token_check_is_audited_and_counts_in_the_cap(world, tmp_path, held_world, switch_on):
    api, gateway = _api_with(world, tmp_path, health_test_per_user_hour=1)
    redis = RedisStub()
    api.app.state.napix_token_cache = TokenCache(redis_client=redis)
    try:
        h = ds.login(api, "root")
        r = api.post(f"{BASE}/token/check", headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True and body["http_status"] == 200 and body["outcome"] == "obtained"
        assert (
            body["expires_in"] == 3600 and body["token"]["held"] is True and body["token"]["status"] == "ok"
        )
        assert body["token"]["check"]["allowed"] is False
        assert gateway.token_calls == 1 and gateway.seen == []
        assert redis.get("napix:token") == b"tok1" and "tok1" not in r.text
        (audit,) = _audits(world, "napix.token_checked")
        assert audit.after == {
            "ok": True,
            "http_status": 200,
            "error_family": None,
            "duration_ms": audit.after["duration_ms"],
            "expires_in": 3600,
            "rate_limit": {"limit": None, "remaining": None},
        }
        r = _send(api, "state", h)
        assert r.status_code == 429 and r.json()["detail"]["code"] == "test_limit"
        assert gateway.seen == []
    finally:
        api.__exit__(None, None, None)


def test_token_check_failure_is_an_outcome(api, world, gw, switch_on):
    import httpx

    def refuse(request):
        gw.token_calls += 1
        return httpx.Response(401, text="no")

    api.app.state.napix_factory = _refusing_factory(refuse)
    r = api.post(f"{BASE}/token/check", headers=ds.login(api, "root"))
    assert r.status_code == 200 and r.json()["ok"] is False and r.json()["http_status"] == 401
    assert r.json()["outcome"] == "refused: check NAPIX_CLIENT_ID / SECRET"
    assert r.json()["token"]["status"] == "down"
    (audit,) = _audits(world, "napix.token_checked")
    assert audit.after["ok"] is False and audit.after["error_family"] == "NapixAuthError"


def _refusing_factory(handler):
    import httpx

    from aslms.integration.napix.client import NapixClient
    from aslms.integration.napix.hc import NapixHighCourt

    def factory():
        c = NapixClient(
            base_url="https://gw.test/nic/ecourts",
            client_id="key-test",
            client_secret="secret-test",
            dept_id="dept-test",
            crypto=NapixCrypto(KEY),
            transport=httpx.MockTransport(handler),
            backoff_base=0.0,
        )
        return c, NapixHighCourt(c, "GAHC01", "18")

    return factory


# ------------------------------------------------------------------------------------------------ the documents


def test_docs_served_inline_with_headers(api, world):
    h = ds.login(api, "root")
    listed = api.get(f"{BASE}/docs", headers=h).json()
    assert [(d["doc"], d["pages"], d["available"]) for d in listed] == [
        ("hc_spec", 85, True),
        ("subscriber_manual", 23, True),
        ("ecourts_spec", 152, True),
    ]
    r = api.get(f"{BASE}/docs/subscriber_manual", headers=h)
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"].startswith("inline;")
    assert r.headers["content-security-policy"] == "sandbox"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"] == "private, no-store"
    ref = api.get(f"{BASE}/napix/token/reference", headers=h).json()
    assert ref["doc"] == {
        "doc": "subscriber_manual",
        "page": 10,
        "section": "2.2 Token Generation",
        "available": True,
    }


def test_docs_missing_or_changed_is_404(world, tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "HighCourt_Open_API_Specifications_1.0_NAPIX_07.09.2023-1-1-1.pdf").write_bytes(
        b"%PDF-1.4 not the pinned edition"
    )
    api = ds.make_api(world, tmp_path, napix_docs_dir=str(docs))
    try:
        h = ds.login(api, "root")
        for doc in ("hc_spec", "subscriber_manual"):
            r = api.get(f"{BASE}/docs/{doc}", headers=h)
            assert r.status_code == 404 and r.json()["detail"]["code"] == "doc_missing", doc
            assert "not installed" in r.json()["detail"]["message"]
        unknown = api.get(f"{BASE}/docs/other", headers=h)
        assert unknown.status_code == 404 and unknown.json()["detail"]["code"] == "not_found"
        assert all(d["available"] is False for d in api.get(f"{BASE}/docs", headers=h).json())
        ref = api.get(f"{BASE}/napix/cnr/reference", headers=h).json()
        assert (
            ref["doc"]["available"] is False and ref["inputs"][0]["name"] == "cino"
        )  # the reference still works
    finally:
        api.__exit__(None, None, None)
