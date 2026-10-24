"""`/admin/system-health` (design `api-health-checker`): who may use the screen, reading never calls the gateway, the
court cards from the call log (answered rule, rates, buckets, percentiles, status rules), the test of each of the 17
court APIs (one call with held inputs, logged, audited, no case data written, nothing personal or secret returned),
the guard's refusals in order, and the outcomes of court failures. The switch is never set: `napix_configured` is
patched as in `test_api_napix_admin.py`."""

from __future__ import annotations

import base64
import json
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
import sqlalchemy as sa
from fastapi import Request

from aslms.core.config import Settings
from aslms.domain.alerts import Alert
from aslms.domain.cases import (
    AdvocateSide,
    Case,
    CaseAdvocate,
    CaseHearing,
    CaseParty,
    HearingSource,
    PartyRole,
)
from aslms.domain.causelists import Causelist, ListSource, ListType
from aslms.domain.courts import Act, Bench, CaseType, Court, District, HighCourt
from aslms.domain.documents import (
    DocGroup,
    DocKind,
    Document,
    Order,
    ScanStatus,
    SourcetraceStatus,
    TextStatus,
    Visibility,
)
from aslms.domain.events import AuditLog, Event
from aslms.domain.ops import FetchQueueItem, NapixCallLog
from aslms.domain.org import PermissionEffect
from aslms.domain.ownership import DiscoveryTerm, OfficeKeyword
from aslms.domain.reference import DocType, Permission
from aslms.integration.napix.client import NapixClient
from aslms.integration.napix.crypto import NapixCrypto
from aslms.integration.napix.hc import NapixHighCourt
from aslms.services import access
from aslms.services import ownership as own
from aslms.services.reporting_common import today_ist
from aslms.services.service_checks import Probes
from tests.db import docs_support as ds
from tests.db.conftest import FIXTURES, SAMPLES, router, sample
from tests.db.world import make_case
from tests.unit.conftest import KEY, Gateway

CNR = "GAHC010277142024"  # in the Search by Case Number sample, so "the source case is among the rows"
ORDER_PDF = (SAMPLES / "order_2026-09-03.pdf").read_bytes()
LIST_PDF = (FIXTURES / "napix_lawazima_bench2048_2025-01-06.pdf").read_bytes()
PARTY = "THE STATE OF ASSAM"
ADVOCATE = "MR. ANUP KUMAR SARMA"
KEYS = (
    "overview",
    "state",
    "district",
    "bench_master",
    "case_type",
    "act",
    "causelist_bench",
    "causelist_details",
    "show_causelist",
    "cnr",
    "current_status",
    "order",
    "show_business",
    "case_search",
    "filing",
    "party_name",
    "advocate_name",
)
NEEDS_DATA = (
    "causelist_details",
    "show_causelist",
    "cnr",
    "current_status",
    "order",
    "show_business",
    "case_search",
    "filing",
    "party_name",
    "advocate_name",
)


def full_router(gw: Gateway, order_pdf: bytes = ORDER_PDF):
    """The conftest router plus the two APIs it does not answer: Order PDF (raw PDF bytes) and Hearing business."""
    base = router(gw)

    def handle(path: str, q: dict, request: httpx.Request) -> httpx.Response:
        if path == "hc-order-api/order":
            return httpx.Response(200, content=order_pdf, headers={"content-type": "application/pdf"})
        if path == "hc-show-business-api/showBusiness":
            return gw.envelope(sample("show_business_pending.json"))
        return base(path, q, request)

    return handle


@pytest.fixture()
def api(world, tmp_path):
    client = ds.make_api(world, tmp_path)
    client.app.state.service_probes = fake_probes()
    yield client
    client.__exit__(None, None, None)


@pytest.fixture()
def gw(api):
    """The scripted gateway behind the API's client factory; each test gets a fresh client (as `open_hc`)."""
    gateway = Gateway(NapixCrypto(KEY))
    gateway.responses = [full_router(gateway)] * 1000
    gateway.clients = []

    def factory():
        client = NapixClient(
            base_url="https://gw.test/nic/ecourts",
            client_id="key-test",
            client_secret="secret-test",
            dept_id="dept-test",
            crypto=NapixCrypto(KEY),
            transport=httpx.MockTransport(gateway.handle),
            backoff_base=0.0,
        )
        gateway.clients.append(client)
        return client, NapixHighCourt(client, "GAHC01", "18")

    api.app.state.napix_factory = factory
    return gateway


@pytest.fixture()
def switch_on(monkeypatch):
    monkeypatch.setattr(Settings, "napix_configured", property(lambda self: True))


def fake_probes(**overrides) -> Probes:
    usage = type("Usage", (), {"free": 500 * 1024**3, "total": 1000 * 1024**3})()
    values = {
        "redis": lambda s: {"ping_ms": 1, "version": "7.4.10", "used": 1024, "max": 0},
        "pg_direct": lambda host, port, timeout: "N",
        "clamav": lambda s: f"ClamAV 1.5.4/27795/{datetime.now(UTC).strftime('%a %b %d %H:%M:%S %Y')}",
        "web": lambda url, timeout: True,
        "store": lambda path: None,
        "disk": lambda path: usage,
        "db_head": lambda s: None,
    }
    values.update(overrides)
    return Probes(**values)


def _grant(world, key: str, perm: Permission = Permission.ADMIN_SERVICE_HEALTH) -> None:
    with world.Session() as s:
        actor, root = world.actor(s, "root")
        access.set_override(s, actor, root, world.user(s, key), perm, PermissionEffect.GRANT, reason="test")
        s.commit()


def _audits(world) -> list[AuditLog]:
    with world.Session() as s:
        return list(
            s.scalars(
                sa.select(AuditLog).where(AuditLog.action == "napix.api_tested").order_by(AuditLog.created_at)
            ).all()
        )


def _count(world, model) -> int:
    with world.Session() as s:
        return int(s.scalar(sa.select(sa.func.count()).select_from(model)) or 0)


def _calls(world) -> list[NapixCallLog]:
    with world.Session() as s:
        return list(s.scalars(sa.select(NapixCallLog).order_by(NapixCallLog.called_at)).all())


def _log(
    s,
    api: str,
    minutes_ago: float,
    *,
    ok=True,
    family=None,
    ms=100,
    user_id=None,
    remaining=None,
    http=None,
    at: datetime | None = None,
):
    """One call-log row `minutes_ago` before `at` (default: the current time)."""
    s.add(
        NapixCallLog(
            api=api,
            params_sha256="0" * 64,
            ok=ok,
            http_status=http,
            error_family=family,
            duration_ms=ms,
            user_id=user_id,
            rate_limit_remaining=remaining,
            called_at=(at or datetime.now(UTC)) - timedelta(minutes=minutes_ago),
        )
    )


@pytest.fixture()
def held(world, api):
    """Data ASLMS holds for every chooser: a fetched case (claimed by Education) with its type, numbers, respondent,
    advocate, a hearing with a business date and a stored order; a stored NAPIX cause list."""
    store = api.store
    with world.Session() as s:
        court = s.scalar(sa.select(Court).where(Court.est_code == "GAHC01"))
        ct = CaseType(court_id=court.id, case_type_code=111, type_name="WP(C)", short_name="WP(C)")
        s.add(ct)
        s.flush()
        case = make_case(s, cnr=CNR, case_no="WP(C)/7714/2024")
        case.case_type_id, case.reg_no, case.reg_year = ct.id, 7714, 2024
        case.filing_case_type_id, case.filing_no, case.filing_year = ct.id, 11883, 2025
        case.last_full_refresh_at = datetime.now(UTC) - timedelta(hours=1)
        s.add(
            CaseParty(
                case_id=case.id, role=PartyRole.RESPONDENT, party_no=1, name=PARTY, name_normalised=PARTY
            )
        )
        s.add(CaseAdvocate(case_id=case.id, side=AdvocateSide.PETITIONER, name_as_listed=ADVOCATE))
        s.add(
            CaseHearing(case_id=case.id, business_date=date(2026, 7, 13), source=HearingSource.SHOW_BUSINESS)
        )
        ds.stored_order(s, store, case, ORDER_PDF, order_no="1", order_date=date(2026, 7, 13))
        stored = store.put(LIST_PDF, "application/pdf")
        doc = Document(
            sha256=stored.sha256,
            storage_key=stored.key,
            mime="application/pdf",
            size_bytes=stored.size,
            kind=DocKind.CAUSELIST,
            doc_type=DocType.CAUSELIST,
            doc_group=DocGroup.COURT_RECORD,
            doc_date=date(2025, 1, 6),
            description="Cause list",
            visibility=Visibility.CASE_SCOPE,
            virus_scan_status=ScanStatus.SKIPPED,
            text_status=TextStatus.NONE,
            sourcetrace_status=SourcetraceStatus.NOT_APPLICABLE,
        )
        s.add(doc)
        s.flush()
        s.add(
            Causelist(
                court_id=court.id,
                list_date=date(2025, 1, 6),
                bench_id=2048,
                napix_causelist_id=1007,
                list_type=ListType.LAWAZIMA,
                source=ListSource.NAPIX,
                document_id=doc.id,
            )
        )
        actor, admin = world.actor(s, "edu_admin")
        own.claim(s, actor, admin, case)
        s.commit()
        return {"case_id": case.id, "ref_no": case.ref_no}


def _post(api, key: str, h: dict):
    return api.post(f"/admin/system-health/napix/{key}/test", headers=h)


ENDPOINTS = (
    ("GET", "/admin/system-health"),
    ("GET", "/admin/system-health/napix/state"),
    ("POST", "/admin/system-health/napix/state/test"),
    ("GET", "/admin/system-health/services"),
)


# ------------------------------------------------------------------------------------------------ who


def test_every_endpoint_needs_admin_service_health(api, world, gw):
    for key in ("edu_off1", "central_op", "oversight", "edu_auditor"):
        h = ds.login(api, key)
        for method, path in ENDPOINTS:
            r = api.request(method, path, headers=h)
            assert r.status_code == 403, (key, path, r.text)
    root = ds.login(api, "root")
    for method, path in ENDPOINTS:
        r = api.request(method, path, headers=root)
        assert r.status_code == (409 if method == "POST" else 200), (path, r.text)  # the switch is off
    _grant(world, "edu_off1")
    h = ds.login(api, "edu_off1")
    for method, path in ENDPOINTS:
        r = api.request(method, path, headers=h)
        assert r.status_code == (409 if method == "POST" else 200), (path, r.text)
    assert gw.seen == []
    me = api.get("/me", headers=root).json()
    assert "admin.service_health" in me["functions"]


def test_reading_never_calls_the_gateway(api, world, gw, held, switch_on):
    h = ds.login(api, "root")
    before = _count(world, NapixCallLog), _count(world, AuditLog)
    body = api.get("/admin/system-health", headers=h).json()
    assert [g["key"] for g in body["groups"]] == ["masters", "causelists", "cases", "searches"]
    assert [c["key"] for g in body["groups"] for c in g["cards"]] == list(KEYS)
    assert all(len(c["hours"]) == 24 for g in body["groups"] for c in g["cards"])
    assert body["summary"] == {"working": 0, "unsteady": 0, "failing": 0, "no_recent": 17, "total": 17}
    assert body["napix_enabled"] is True and body["window"]["status"] == "unknown"
    for key in KEYS:
        d = api.get(f"/admin/system-health/napix/{key}", headers=h)
        assert d.status_code == 200, (key, d.text)
        assert len(d.json()["days"]) == 7 and d.json()["sample"]["available"] is True
    svc = api.get("/admin/system-health/services", headers=h).json()
    assert [x["key"] for x in svc["services"]] == [
        "api",
        "db_pool",
        "db_direct",
        "redis",
        "worker",
        "scheduler",
        "clamav",
        "backups",
        "store",
        "web",
    ]
    assert gw.seen == [] and gw.token_calls == 0
    assert (_count(world, NapixCallLog), _count(world, AuditLog)) == before


def test_unknown_api_is_404(api, world, gw, switch_on):
    h = ds.login(api, "root")
    for r in (api.get("/admin/system-health/napix/cnr_alt", headers=h), _post(api, "neutral_citation", h)):
        assert r.status_code == 404 and r.json()["detail"]["code"] == "not_found"
    assert gw.seen == []


# ------------------------------------------------------------------------------------------------ the cards


def test_cards_count_not_found_and_input_refusals_as_answered(api, world):
    path = "hc-state-api/state"
    with world.Session() as s:
        for i, ms in enumerate((100, 200, 300)):
            _log(s, path, 10 + i, ms=ms)
        _log(s, path, 20, ok=False, family="NapixNotFound", ms=400)
        _log(s, path, 30, ok=False, family="NapixInputError", ms=500)
        _log(s, path, 40, ok=False, family="NapixUnavailable", ms=600)
        _log(s, path, 3 * 24 * 60, ms=1000)
        _log(s, path, 3 * 24 * 60 + 1, ok=False, family="NapixEmptyResponse", ms=1000)
        _log(s, path, 8 * 24 * 60)  # outside the week
        s.commit()
    body = api.get("/admin/system-health", headers=ds.login(api, "root")).json()
    card = body["groups"][0]["cards"][1]
    assert card["key"] == "state"
    assert card["h24"] == {
        "calls": 6,
        "answered": 5,
        "failed": 1,
        "rate": round(5 / 6, 4),
        "p50_ms": 350,
        "p95_ms": 575,
    }
    assert card["d7"] == {"calls": 8, "answered": 6, "failed": 2, "rate": 0.75}
    assert sum(b["answered"] for b in card["hours"]) == 5 and sum(b["failed"] for b in card["hours"]) == 1
    assert card["last_call"]["answered"] is True and card["last_call"]["by"] == "background"
    assert card["status"] == "warn"  # 83 % answered over at least 5 calls in 24 h is below 90 %
    detail = api.get("/admin/system-health/napix/state", headers=ds.login(api, "root")).json()
    assert sum(d["calls"] for d in detail["days"]) == 8
    assert len(detail["recent"]) == 8 and detail["recent"][0]["duration_ms"] == 100
    assert {r["reason"] for r in detail["recent"] if r["error_family"] == "NapixNotFound"} == {
        "The court answered: no record found for this input"
    }
    assert detail["technical"] == {
        "name": "state",
        "path": "hc-state-api/state",
        "method": "GET",
        "input_fields": [],
    }


def test_card_status_rules(api, world):
    with world.Session() as s:
        root_id = world.user(s, "root").id
        for i in range(5):
            _log(s, "hc-state-api/state", 10 + i)
        _log(s, "hc-district-api/district", 1, ok=False, family="NapixUnavailable")
        for i in range(9):
            _log(s, "hc-district-api/district", 10 + i)
        for i in range(3):
            _log(s, "hc-bench-master-api/bench", 1 + i, ok=False, family="NapixGatewayError")
        for i in range(5):
            _log(s, "hc-act-master-api/actMaster", 10 + i, ms=25_000)
        _log(s, "hc-case-type-master-api/casetypemaster", 1, user_id=root_id)
        s.commit()
    body = api.get("/admin/system-health", headers=ds.login(api, "root")).json()
    status = {c["key"]: (c["status"], c["status_word"]) for c in body["groups"][0]["cards"]}
    assert status == {
        "overview": ("unknown", "No recent calls"),
        "state": ("ok", "Working"),
        "district": ("warn", "Unsteady"),
        "bench_master": ("down", "Failing"),
        "case_type": ("ok", "Working"),
        "act": ("warn", "Unsteady"),
    }
    case_type = body["groups"][0]["cards"][4]
    assert case_type["last_call"]["by"] == "you"
    assert body["summary"] == {"working": 2, "unsteady": 2, "failing": 1, "no_recent": 12, "total": 17}


def test_cnr_alt_rows_are_not_counted(api, world):
    with world.Session() as s:
        for i in range(4):
            _log(s, "hc-cnr-api/cnr", 5 + i, ok=False, family="NapixGatewayError")
        s.commit()
    body = api.get("/admin/system-health", headers=ds.login(api, "root")).json()
    cnr = next(c for g in body["groups"] for c in g["cards"] if c["key"] == "cnr")
    assert cnr["status"] == "unknown" and cnr["h24"]["calls"] == 0 and cnr["d7"]["calls"] == 0


# ------------------------------------------------------------------------------------------------ the test


def test_switch_off_refuses_without_a_call_or_audit(api, world, gw, held):
    h = ds.login(api, "root")
    before = _count(world, NapixCallLog), _count(world, AuditLog)
    r = _post(api, "state", h)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "napix_off"
    assert "NAPIX_ENABLED is false" in r.json()["detail"]["message"]
    assert (_count(world, NapixCallLog), _count(world, AuditLog)) == before and gw.seen == []
    card = api.get("/admin/system-health", headers=h).json()["groups"][0]["cards"][1]
    assert card["test"]["available"] is False and "switched off" in card["test"]["reason"]


EXPECTED = {
    "overview": ("overview/overview", "", "GET"),
    "state": ("hc-state-api/state", "", "GET"),
    "district": ("hc-district-api/district", "state_code=18", "GET"),
    "bench_master": ("hc-bench-master-api/bench", "state_code=18", "GET"),
    "case_type": ("hc-case-type-master-api/casetypemaster", "est_code=GAHC01", "GET"),
    "act": ("hc-act-master-api/actMaster", "", "GET"),
    "causelist_bench": (
        "hc-causelist-bench-api/causelistbench",
        "est_code=GAHC01|causelist_date=2025-01-06",
        "GET",
    ),
    "causelist_details": (
        "hc-causelist-details-api/causelistdetails",
        "est_code=GAHC01|causelist_date=2025-01-06|bench_id=2048",
        "GET",
    ),
    "show_causelist": (
        "hc-show-causelist-api/showcauselist",
        "est_code=GAHC01|bench_id=2048|causelist_id=1007|causelist_date=2025-01-06",
        "GET",
    ),
    "cnr": ("hc-cnr-api/CNR", f"cino={CNR}", "GET"),
    "current_status": ("hc-current-status-api/currentStatus", f"cino={CNR}", "POST"),
    "order": ("hc-order-api/order", f"cino={CNR}|order_no=1|order_date=2026-07-13", "GET"),
    "show_business": ("hc-show-business-api/showBusiness", f"cino={CNR}|business_date=2026-07-13", "GET"),
    "case_search": (
        "hc-case-search-api/casesearch",
        "est_code=GAHC01|case_type=111|reg_no=7714|reg_year=2024",
        "GET",
    ),
    "filing": ("hc-filing-api/Filing", "est_code=GAHC01|case_type=111|fil_no=11883|fil_year=2025", "GET"),
    "party_name": (
        "hc-party-name-api/partyname",
        f"est_code=GAHC01|pend_disp=P|litigant_name={PARTY}|reg_year=2024",
        "GET",
    ),
    "advocate_name": (
        "hc-advocate-name-api/advocatename",
        f"est_code=GAHC01|pend_disp=P|advocate_name={ADVOCATE}|reg_year=2024",
        "GET",
    ),
}


@pytest.mark.parametrize("key", KEYS)
def test_each_api_makes_exactly_one_call_with_held_inputs(api, world, gw, held, switch_on, key):
    h = ds.login(api, "root")
    r = _post(api, key, h)
    assert r.status_code == 200, r.text
    body = r.json()
    path, plain, method = EXPECTED[key]
    assert [(x["path"], x["plain"], x["method"]) for x in gw.seen] == [(path, plain, method)]
    assert body["api"] == key and body["ok"] is True and body["answered"] is True and body["status"] == "ok"
    assert body["attempts"] == 1 and body["reason"] == "The court answered"
    assert gw.clients[-1].max_attempts == 1 and gw.clients[-1].timeout == 30
    with world.Session() as s:
        root_id = world.user(s, "root").id
    logged = _calls(world)
    assert [(c.api, c.user_id, c.lane, c.job_run_id) for c in logged] == [(path, root_id, None, None)]
    (audit,) = _audits(world)
    assert audit.entity_type == "napix" and audit.entity_id is None and audit.case_id is None
    assert audit.after["api"] == key and audit.after["path"] == path and audit.after["attempts"] == 1
    assert audit.actor_user_id == root_id
    if key in NEEDS_DATA and key not in ("causelist_details", "show_causelist"):
        assert audit.after["sample"]["case_ref_no"] == held["ref_no"]
    assert body["summary"]["kind"] in ("rows", "record", "pdf")


def test_summaries_carry_the_computed_facts(api, world, gw, held, switch_on):
    h = ds.login(api, "root")

    def facts(key):
        r = _post(api, key, h)
        assert r.status_code == 200, r.text
        return r.json()["summary"], {f["label"]: f["value"] for f in r.json()["summary"]["facts"]}

    summary, f = facts("overview")
    assert summary["kind"] == "record" and f["Version"] == "v1.0"
    summary, f = facts("case_search")
    assert summary == summary | {"kind": "rows", "row_count": 1}
    assert f == {
        "Distinct cases (CNR)": "1",
        "The source case is among the rows": "yes",
        "Of them held by ASLMS": "1",
    }
    assert "pet_name" in summary["field_names"]
    summary, f = facts("cnr")
    assert f["The CNR in the answer is the one asked"] == "yes" and f["Case status"] == "pending"
    assert f["Hearings in the answer"] == "3"
    summary, f = facts("causelist_details")
    assert f["List names"] == "LAWAZIMA"
    summary, f = facts("show_causelist")
    assert summary["kind"] == "pdf" and f["Same as the stored copy"] == "yes" and int(f["Pages"]) >= 1
    summary, f = facts("show_business")
    assert f == {"The business date matches": "yes", "Business text is present": "yes"}


def test_no_held_data_means_no_sample_and_no_call(api, world, gw, switch_on):
    h = ds.login(api, "root")
    for key in NEEDS_DATA:
        r = _post(api, key, h)
        assert r.status_code == 409, (key, r.text)
        assert r.json()["detail"]["code"] == "no_sample" and r.json()["detail"]["message"]
    assert gw.seen == [] and _audits(world) == []
    body = api.get("/admin/system-health", headers=h).json()
    reasons = {c["key"]: c["test"] for g in body["groups"] for c in g["cards"]}
    assert reasons["cnr"] == {
        "available": False,
        "reason": "No case has been fetched from the court yet",
        "cost": 1,
        "next_allowed_at": None,
    }
    for key in ("overview", "state", "district", "bench_master", "case_type", "act", "causelist_bench"):
        assert reasons[key]["available"] is True, key
    for key in ("overview", "state", "district", "bench_master", "case_type", "act", "causelist_bench"):
        assert _post(api, key, h).status_code == 200, key
    assert gw.seen[-1]["plain"] == f"est_code=GAHC01|causelist_date={today_ist().isoformat()}"
    assert len(gw.seen) == 7


def test_party_search_prefers_a_discovery_term(api, world, gw, held, switch_on):
    with world.Session() as s:
        s.add(OfficeKeyword(office_id=world.office(s, "EDU").id, keyword="ANIL BORA", discover=True))
        s.add(DiscoveryTerm(term="ANIL BORA", last_searched_at=datetime.now(UTC)))
        s.commit()
    h = ds.login(api, "root")
    detail = api.get("/admin/system-health/napix/party_name", headers=h).json()
    assert detail["sample"]["values"] == {"reg_year": today_ist().year, "pend_disp": "P", "term": "ANIL BORA"}
    r = _post(api, "party_name", h)
    assert r.status_code == 200, r.text
    assert (
        gw.seen[0]["plain"]
        == f"est_code=GAHC01|pend_disp=P|litigant_name=ANIL BORA|reg_year={today_ist().year}"
    )
    assert "case_ref_no" not in _audits(world)[0].after["sample"]


def test_names_leave_the_server_only_as_the_value_sent(api, world, gw, held, switch_on):
    """Row 109 kept every name on the server; design `system-health-inspector` (decisions 6 and 8) shows the name a
    send used in its request and keeps it in the audit row's `params`, because the sender could see the case. The
    History panel still never shows a name, and no name of the court's answer ever leaves the server."""
    h = ds.login(api, "root")
    sent = {"party_name": PARTY, "advocate_name": ADVOCATE}
    answer_names: set[str] = set()
    for f in ("party_name_2026-09-03.json", "advocate_name_2026-10-18-p1.json"):
        for row in sample(f)["casenos"].values():
            answer_names.update(n for n in (row.get("pet_name"), row.get("res_name")) if n)
    for key in ("party_name", "advocate_name"):
        detail = api.get(f"/admin/system-health/napix/{key}", headers=h)
        assert not [n for n in answer_names | set(sent.values()) if n in detail.text], key
        r = _post(api, key, h)
        assert r.status_code == 200, r.text
        assert sent[key] in r.json()["request"]["plain"]
        assert not [n for n in answer_names - {sent[key]} if n in r.text], key
        assert "of WP(C)/7714/2024" in r.json()["input"]["label"]
    for audit in _audits(world):
        key = audit.after["api"]
        assert sent[key] in audit.after["params"].values()
        dumped = json.dumps({k: v for k, v in audit.after.items() if k != "params"})
        assert not [n for n in answer_names | set(sent.values()) if n in dumped]


def test_sample_label_names_the_case_only_when_visible(api, world, gw, held):
    _grant(world, "edu_admin")
    _grant(world, "health_admin")
    seen = api.get("/admin/system-health/napix/cnr", headers=ds.login(api, "edu_admin")).json()["sample"]
    assert CNR in seen["label"] and seen["values"] == {"cnr": CNR}
    hidden = api.get("/admin/system-health/napix/cnr", headers=ds.login(api, "health_admin")).json()["sample"]
    assert hidden["label"] == "a case held by ASLMS" and hidden["values"] == {}
    adv = api.get("/admin/system-health/napix/advocate_name", headers=ds.login(api, "health_admin")).json()
    assert adv["sample"]["label"].startswith("An advocate of a case held by ASLMS")
    assert "WP(C)/7714" not in json.dumps(adv)


def test_response_has_no_secret_or_token(api, world, gw, held, switch_on):
    h = ds.login(api, "root")
    texts = [_post(api, key, h).text for key in ("overview", "cnr")]
    dumped = texts + [json.dumps(a.after) for a in _audits(world)]
    for secret in ("secret-test", "tok1", "tok2", KEY, "dept-test", "key-test"):
        assert not [t for t in dumped if secret in t], secret


def test_test_writes_no_case_data(api, world, gw, held, switch_on):
    from aslms.domain.cases import CaseParty as Party

    tables = (
        Case,
        Party,
        CaseAdvocate,
        CaseHearing,
        Order,
        Document,
        Causelist,
        FetchQueueItem,
        Event,
        Alert,
    )
    masters = (HighCourt, District, Court, CaseType, Act, Bench)
    before = {m.__name__: _count(world, m) for m in tables + masters}
    with world.Session() as s:
        responses = s.scalar(sa.text("SELECT count(*) FROM napix_responses"))
    h = ds.login(api, "root")
    for key in ("cnr", "order", "state", "show_causelist", "party_name"):
        assert _post(api, key, h).status_code == 200, key
    assert {m.__name__: _count(world, m) for m in tables + masters} == before
    with world.Session() as s:
        after = s.scalar(sa.text("SELECT count(*) FROM napix_responses"))
    assert after == responses + 3  # the three JSON answers; the two PDFs are hashed and discarded


# ------------------------------------------------------------------------------------------------ court failures


def test_a_gateway_500_is_one_attempt_and_a_failed_outcome(api, world, gw, held, switch_on):
    gw.responses = [lambda p, q, r: httpx.Response(500, text="boom")]
    r = _post(api, "state", ds.login(api, "root"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False and body["answered"] is False and body["status"] == "down"
    assert body["error_family"] == "NapixUnavailable" and body["http_status"] == 500 and body["attempts"] == 1
    assert "boom" not in r.text
    assert len(gw.seen) == 1 and len(_calls(world)) == 1
    (audit,) = _audits(world)
    assert audit.after["ok"] is False and audit.after["error_family"] == "NapixUnavailable"
    card = api.get("/admin/system-health", headers=ds.login(api, "root")).json()["groups"][0]["cards"][1]
    assert card["status"] == "warn" and card["last_call"]["answered"] is False


def test_empty_200_is_reported_as_the_known_fault(api, world, gw, held, switch_on):
    gw.responses = [lambda p, q, r: httpx.Response(200, text="")]
    body = _post(api, "cnr", ds.login(api, "root")).json()
    assert body["error_family"] == "NapixEmptyResponse" and body["ok"] is False
    assert "empty answer" in body["reason"] and len(gw.seen) == 1


def test_628_reads_answered(api, world, gw, held, switch_on):
    gw.responses = [lambda p, q, r: gw.encrypted_status(628)]
    body = _post(api, "cnr", ds.login(api, "root")).json()
    assert body["ok"] is False and body["answered"] is True and body["status"] == "warn"
    assert body["error_family"] == "NapixNotFound" and body["napix_status"] == 628
    card = next(
        c
        for g in api.get("/admin/system-health", headers=ds.login(api, "root")).json()["groups"]
        for c in g["cards"]
        if c["key"] == "cnr"
    )
    assert card["status"] == "ok" and card["h24"]["answered"] == 1


def test_cnr_404_never_tries_the_alternate_path(api, world, gw, held, switch_on):
    gw.responses = [lambda p, q, r: httpx.Response(404, text="no")] * 3
    body = _post(api, "cnr", ds.login(api, "root")).json()
    assert body["error_family"] == "NapixGatewayError" and body["attempts"] == 1
    assert [x["path"] for x in gw.seen] == ["hc-cnr-api/CNR"]


def _card(api, h: dict, key: str) -> dict:
    body = api.get("/admin/system-health", headers=h).json()
    return next(c for g in body["groups"] for c in g["cards"] if c["key"] == key)


def test_token_renewal_counts_two_attempts(api, world, gw, held, switch_on):
    gw.responses = [lambda p, q, r: httpx.Response(401, text="")] + [full_router(gw)] * 5
    h = ds.login(api, "root")
    body = _post(api, "state", h).json()
    assert body["ok"] is True and body["attempts"] == 2 and body["http_status"] == 200 and gw.token_calls == 2
    calls = _calls(world)
    assert [(c.http_status, c.ok, c.error_family) for c in calls] == [(401, False, None), (200, True, None)]
    assert _audits(world)[0].after["attempts"] == 2
    card = _card(api, h, "state")
    assert card["h24"]["calls"] == 1 and card["h24"]["answered"] == 1 and card["status"] == "ok"
    detail = api.get("/admin/system-health/napix/state", headers=h).json()
    assert [r["http_status"] for r in detail["recent"]] == [200]


def test_renewal_failure_counts_once(api, world, gw, held, switch_on):
    gw.responses = [lambda p, q, r: httpx.Response(401), lambda p, q, r: httpx.Response(500)]
    h = ds.login(api, "root")
    body = _post(api, "state", h).json()
    assert body["status"] == "down" and body["error_family"] == "NapixUnavailable" and body["attempts"] == 2
    assert [(c.http_status, c.error_family) for c in _calls(world)] == [
        (401, None),
        (500, "NapixUnavailable"),
    ]
    card = _card(api, h, "state")
    assert card["h24"]["calls"] == 1 and card["h24"]["answered"] == 0


def test_past_renewal_rows_are_not_counted(api, world):
    path = "hc-state-api/state"
    with world.Session() as s:
        _log(s, path, 30, http=200)
        for minutes in (
            1,
            2,
            3,
        ):  # renewal steps after it: counted, they would make the last three all failed
            _log(s, path, minutes, ok=False, http=401)
        s.commit()
    h = ds.login(api, "root")
    card = _card(api, h, "state")
    assert card["h24"]["calls"] == 1 and card["h24"]["rate"] == 1.0 and card["d7"]["calls"] == 1
    assert card["status"] == "ok" and card["last_call"]["answered"] is True
    detail = api.get("/admin/system-health/napix/state", headers=h).json()
    assert [r["http_status"] for r in detail["recent"]] == [200]
    with world.Session() as s:  # the rows stay in the call log
        assert s.scalar(sa.select(sa.func.count()).select_from(NapixCallLog)) == 4


# ------------------------------------------------------------------------------------------------ recorded apart


def _responses(world) -> int:
    with world.Session() as s:
        return int(s.scalar(sa.text("SELECT count(*) FROM napix_responses")) or 0)


def test_call_rows_survive_a_failure_after_the_call(api, world, gw, held, switch_on, monkeypatch):
    from aslms.services import napix_api_check

    real = napix_api_check._summary

    def broken(*args, **kwargs):
        raise RuntimeError("summary defect")

    monkeypatch.setattr(napix_api_check, "_summary", broken)
    h = ds.login(api, "root")
    with pytest.raises(RuntimeError, match="summary defect"):  # the request answers 500
        _post(api, "state", h)
    with world.Session() as s:
        root_id = world.user(s, "root").id
    assert [(c.api, c.user_id) for c in _calls(world)] == [("hc-state-api/state", root_id)]
    assert _responses(world) == 1
    (audit,) = _audits(world)
    assert audit.after["summary"] is None and audit.after["summary_error"] == "RuntimeError"
    assert audit.after["ok"] is True and audit.actor_user_id == root_id
    monkeypatch.setattr(napix_api_check, "_summary", real)
    r = _post(api, "state", h)
    assert r.status_code == 429 and r.json()["detail"]["code"] == "test_too_soon"
    assert len(gw.seen) == 1


def test_call_rows_survive_a_failed_audit(api, world, gw, held, switch_on, monkeypatch):
    from aslms.services import audit

    def broken(*args, **kwargs):
        raise RuntimeError("audit store down")

    monkeypatch.setattr(audit, "write_audit_apart", broken)
    h = ds.login(api, "root")
    with pytest.raises(RuntimeError, match="audit store down"):
        _post(api, "state", h)
    assert len(_calls(world)) == 1 and _responses(world) == 1
    assert _audits(world) == []


def test_a_person_runs_one_test_at_a_time(api, world, gw, held, switch_on, engine):
    with world.Session() as s:
        root_id = world.user(s, "root").id
    h = ds.login(api, "root")
    with engine.connect() as conn, conn.begin():
        conn.execute(
            sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
            {"k": f"napix-api-test-user:{root_id}"},
        )
        r = _post(api, "state", h)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "user_test_running"
        assert "other test is still running" in r.json()["detail"]["message"]
    assert gw.seen == [] and _audits(world) == [] and _calls(world) == []
    assert _post(api, "district", h).status_code == 200


def test_cap_checked_again_after_the_locks(world, tmp_path, switch_on, monkeypatch):
    from aslms.services import napix_api_check
    from aslms.services.audit import write_audit

    api, gateway = _api_with(world, tmp_path, health_test_per_user_hour=1)
    try:
        real = napix_api_check.lock_user

        def racing(session, user_id):
            # another request of the same person committed its test between this one's guard and its locks
            with world.Session() as s:
                actor, _ = world.actor(s, "root")
                write_audit(s, actor, "napix.api_tested", "napix", None, after={"api": "act", "ok": True})
                s.commit()
            real(session, user_id)

        monkeypatch.setattr(napix_api_check, "lock_user", racing)
        r = _post(api, "state", ds.login(api, "root"))
        assert r.status_code == 429 and r.json()["detail"]["code"] == "test_limit"
        assert gateway.seen == [] and _calls(world) == []
    finally:
        api.__exit__(None, None, None)


def test_request_transaction_writes_nothing(api, world, gw, held, switch_on):
    """The seam: `get_session` is overridden to read `pg_current_xact_id_if_assigned()` just before the request
    session commits. PostgreSQL assigns a transaction id only on a write, so NULL proves the request transaction wrote
    nothing (advisory locks and reads do not assign one)."""
    from aslms.api.deps import get_session

    h = ds.login(api, "root")
    xids: list = []

    def recording(request: Request):
        session = request.app.state.session_factory()
        try:
            yield session
            xids.append(session.scalar(sa.text("SELECT pg_current_xact_id_if_assigned()")))
            session.commit()
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    api.app.dependency_overrides[get_session] = recording
    try:
        r = _post(api, "state", h)
    finally:
        api.app.dependency_overrides.clear()
    assert r.status_code == 200, r.text
    assert xids == [None]
    assert len(_calls(world)) == 1 and len(_audits(world)) == 1


def test_pdf_summary_compares_with_the_stored_copy(api, world, gw, held, switch_on):
    h = ds.login(api, "root")
    same = {f["label"]: f["value"] for f in _post(api, "order", h).json()["summary"]["facts"]}
    assert same["Same as the stored copy"] == "yes" and same["Size"].endswith("KB")
    other = (SAMPLES / "order_2026-10-01.pdf").read_bytes()
    gw.responses = [full_router(gw, order_pdf=other)]
    with world.Session() as s:  # the per-API interval: move the first test back in time
        s.execute(sa.text("SET session_replication_role = replica"))  # audit_log is append-only
        s.execute(sa.text("UPDATE audit_log SET created_at = created_at - interval '2 minutes'"))
        s.commit()
    diff = {f["label"]: f["value"] for f in _post(api, "order", h).json()["summary"]["facts"]}
    assert diff["Same as the stored copy"] == "no"


# ------------------------------------------------------------------------------------------------ the guard


def test_per_api_interval(api, world, gw, held, switch_on):
    _grant(world, "central_op")
    assert _post(api, "state", ds.login(api, "root")).status_code == 200
    r = _post(api, "state", ds.login(api, "central_op"))
    assert r.status_code == 429 and r.json()["detail"]["code"] == "test_too_soon"
    assert 1 <= int(r.headers["Retry-After"]) <= 60 and r.json()["detail"]["retry_after"] >= 1
    assert len(gw.seen) == 1 and len(_audits(world)) == 1
    card = api.get("/admin/system-health", headers=ds.login(api, "central_op")).json()["groups"][0]["cards"][
        1
    ]
    assert card["test"]["available"] is False and card["test"]["next_allowed_at"] is not None
    assert card["last_test"]["ok"] is True and card["last_test"]["by_you"] is False
    assert _post(api, "district", ds.login(api, "central_op")).status_code == 200


def test_connection_check_shares_the_check_interval(api, world, gw, held, switch_on):
    assert api.post("/admin/napix/health/check", headers=ds.login(api, "central_op")).status_code == 200
    r = _post(api, "overview", ds.login(api, "root"))
    assert r.status_code == 429 and r.json()["detail"]["code"] == "test_too_soon"
    assert len(gw.seen) == 1


def test_per_user_hourly_cap(world, tmp_path, held_cap, switch_on):
    api, gw = held_cap
    h = ds.login(api, "root")
    assert _post(api, "state", h).status_code == 200
    assert _post(api, "district", h).status_code == 200
    r = _post(api, "act", h)
    assert r.status_code == 429 and r.json()["detail"]["code"] == "test_limit"
    assert int(r.headers["Retry-After"]) > 3000 and len(gw.seen) == 2
    card = api.get("/admin/system-health", headers=h).json()["groups"][0]["cards"][5]
    assert card["test"]["available"] is False and "limit is 2" in card["test"]["reason"]


def _api_with(world, tmp_path, **overrides):
    """An API with its own settings and a scripted gateway behind its client factory."""
    client = ds.make_api(world, tmp_path, **overrides)
    client.app.state.service_probes = fake_probes()
    gateway = Gateway(NapixCrypto(KEY))
    gateway.responses = [full_router(gateway)] * 100

    def factory():
        c = NapixClient(
            base_url="https://gw.test/nic/ecourts",
            client_id="key-test",
            client_secret="secret-test",
            dept_id="dept-test",
            crypto=NapixCrypto(KEY),
            transport=httpx.MockTransport(gateway.handle),
            backoff_base=0.0,
        )
        return c, NapixHighCourt(c, "GAHC01", "18")

    client.app.state.napix_factory = factory
    return client, gateway


@pytest.fixture()
def held_cap(world, tmp_path):
    client = ds.make_api(world, tmp_path, health_test_per_user_hour=2)
    client.app.state.service_probes = fake_probes()
    gateway = Gateway(NapixCrypto(KEY))
    gateway.responses = [full_router(gateway)] * 100

    def factory():
        c = NapixClient(
            base_url="https://gw.test/nic/ecourts",
            client_id="key-test",
            client_secret="secret-test",
            dept_id="dept-test",
            crypto=NapixCrypto(KEY),
            transport=httpx.MockTransport(gateway.handle),
            backoff_base=0.0,
        )
        return c, NapixHighCourt(c, "GAHC01", "18")

    client.app.state.napix_factory = factory
    yield client, gateway
    client.__exit__(None, None, None)


def test_quota_floor(api, world, gw, held, switch_on):
    with world.Session() as s:
        _log(s, "hc-cnr-api/CNR", 0.2, remaining=10)
        s.commit()
    r = _post(api, "state", ds.login(api, "root"))
    assert r.status_code == 429 and r.json()["detail"]["code"] == "napix_budget"
    assert int(r.headers["Retry-After"]) == 180  # no reset seen yet: one probe interval
    assert "tests resume after about" in r.json()["detail"]["message"]
    assert gw.seen == [] and _audits(world) == []


def test_unknown_window_allows_a_test(api, world, gw, held, switch_on):
    assert (
        api.get("/admin/system-health", headers=ds.login(api, "root")).json()["window"]["remaining"] is None
    )
    assert _post(api, "state", ds.login(api, "root")).status_code == 200


def test_concurrent_test_of_one_api_is_refused(api, world, gw, held, switch_on, engine):
    with engine.connect() as conn, conn.begin():
        conn.execute(sa.text("SELECT pg_advisory_xact_lock(hashtextextended('napix-api-test:state', 0))"))
        r = _post(api, "state", ds.login(api, "root"))
        assert r.status_code == 409 and r.json()["detail"]["code"] == "test_running"
    assert gw.seen == [] and _audits(world) == []
    assert _post(api, "state", ds.login(api, "root")).status_code == 200


def test_cause_list_pdf_in_base64_is_hashed(api, world, gw, held, switch_on):
    """The router answers Show Cause List as a JSON string holding the Base64 PDF (as live)."""
    assert base64.b64encode(LIST_PDF)  # the fixture is a PDF
    body = _post(api, "show_causelist", ds.login(api, "root")).json()
    assert body["summary"]["kind"] == "pdf" and body["summary"]["field_names"] == []
