"""`/admin/data-health`, `/admin/napix/*`, `/admin/failures` (design `audit-screens`, decisions 5-11): who reads the
screen, the buttons enqueue and audit without calling NAPIX, the rules of each button, the one connectivity check
(logged, audited, refused without a call) and the audited CLI re-fetch."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
import sqlalchemy as sa

from aslms.core.config import Settings
from aslms.domain.cases import Case
from aslms.domain.documents import DownloadStatus, Order
from aslms.domain.events import AuditLog
from aslms.domain.ops import FetchKind, FetchQueueItem, FetchStatus, NapixCallLog
from aslms.domain.org import PermissionEffect
from aslms.domain.reference import Permission
from aslms.integration.napix.client import NapixClient
from aslms.integration.napix.crypto import NapixCrypto
from aslms.integration.napix.hc import NapixHighCourt
from aslms.services import access
from aslms.services import ownership as own
from aslms.services.reporting_common import today_ist
from tests import samplefiles as sf
from tests.db import docs_support as ds
from tests.db.conftest import sample
from tests.db.world import make_case
from tests.unit.conftest import KEY, Gateway


@pytest.fixture()
def api(world, tmp_path):
    client = ds.make_api(world, tmp_path)
    yield client
    client.__exit__(None, None, None)


@pytest.fixture()
def gateway(api):
    """The scripted NAPIX gateway behind the API's client factory; `gw.seen` lists every API request."""
    gw = Gateway(NapixCrypto(KEY))

    def factory():
        client = NapixClient(
            base_url="https://gw.test/nic/ecourts",
            client_id="key-test",
            client_secret="secret-test",
            dept_id="dept-test",
            crypto=NapixCrypto(KEY),
            transport=httpx.MockTransport(gw.handle),
            backoff_base=0.0,
        )
        return client, NapixHighCourt(client, "GAHC01", "18")

    api.app.state.napix_factory = factory
    return gw


@pytest.fixture()
def switch_on(monkeypatch):
    """The API process sees NAPIX as configured (the switch itself is never set)."""
    monkeypatch.setattr(Settings, "napix_configured", property(lambda self: True))


def _grant(world, key: str, perm: Permission, effect=PermissionEffect.GRANT) -> None:
    with world.Session() as s:
        actor, root = world.actor(s, "root")
        access.set_override(s, actor, root, world.user(s, key), perm, effect, reason="test")
        s.commit()


def _audits(world, action: str) -> list[AuditLog]:
    with world.Session() as s:
        return list(
            s.scalars(
                sa.select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.created_at)
            ).all()
        )


def _count(world, model) -> int:
    with world.Session() as s:
        return s.scalar(sa.select(sa.func.count()).select_from(model))


def _row(world, kind: FetchKind, ref: str) -> FetchQueueItem | None:
    with world.Session() as s:
        return s.scalar(
            sa.select(FetchQueueItem).where(FetchQueueItem.kind == kind, FetchQueueItem.ref == ref)
        )


def _put(world, kind: FetchKind, ref: str, status: FetchStatus, **kw) -> uuid.UUID:
    with world.Session() as s:
        row = FetchQueueItem(kind=kind, ref=ref, status=status, priority=kw.pop("priority", 60), **kw)
        s.add(row)
        s.commit()
        return row.id


@pytest.fixture()
def edu_case(world):
    with world.Session() as s:
        case = make_case(s)
        actor, admin = world.actor(s, "edu_admin")
        own.claim(s, actor, admin, case)
        s.commit()
        return case


# ------------------------------------------------------------------------------------------------ reading


def test_health_permissions(api, world):
    for key in ("oversight", "central_op", "root"):
        h = ds.login(api, key)
        for path in ("/admin/data-health", "/admin/napix/health", "/admin/napix/queue", "/admin/napix/calls"):
            r = api.get(path, headers=h)
            assert r.status_code == 200, (key, path, r.text)
        assert api.get("/admin/failures", headers=h).status_code == 200
    for key in ("edu_auditor", "edu_off1"):
        h = ds.login(api, key)
        for path in ("/admin/data-health", "/admin/napix/health", "/admin/failures"):
            assert api.get(path, headers=h).status_code == 403, (key, path)
        assert api.post("/admin/napix/sync-masters", headers=h).status_code == 403
    # State oversight reads the screen but presses no button
    h = ds.login(api, "oversight")
    assert api.post("/admin/napix/sync-masters", headers=h).status_code == 403
    assert api.post("/admin/napix/refetch/day", json={"date": "2025-01-06"}, headers=h).status_code == 403
    assert api.post("/admin/napix/health/check", headers=h).status_code == 403


def test_screen_shapes_through_the_api(api, world):
    _put(world, FetchKind.DOSSIER, "ASHC010000012025", FetchStatus.FAILED, last_error="boom")
    with world.Session() as s:
        s.add(
            NapixCallLog(api="hc-cnr-api/CNR", params_sha256="0" * 64, ok=True, called_at=datetime.now(UTC))
        )
        s.commit()
    h = ds.login(api, "central_op")
    body = api.get("/admin/data-health", headers=h).json()
    assert body["queue"]["failed_total"] == 1
    assert [d["label"] for d in body["daily_cycle"]] == ["yesterday", "today", "tomorrow"]
    assert body["napix"]["enabled"] is False and body["napix"]["today"]["calls"] == 1
    assert body["as_of"].endswith("+05:30")
    q = api.get("/admin/napix/queue", params={"status": "failed"}, headers=h).json()
    assert q["total"] == 1 and q["items"][0]["last_error"] == "boom"
    calls = api.get("/admin/napix/calls", headers=h).json()
    assert len(calls["items"]) == 1 and "params" not in calls["items"][0]
    bad = api.get("/admin/napix/calls", params={"cursor": "garbage"}, headers=h)
    assert bad.status_code == 400 and bad.json()["detail"]["code"] == "bad_cursor"
    assert api.get("/admin/napix/queue", params={"kind": "nonsense"}, headers=h).status_code == 422


# ------------------------------------------------------------------------------------------------ buttons


def test_buttons_enqueue_and_audit_without_calling_napix(api, world, gateway, edu_case):
    with world.Session() as s:
        o = ds.pending_order(s, s.get(Case, edu_case.id))
        o.download_status = DownloadStatus.NOT_AVAILABLE
        s.commit()
        order_id, order_ref = o.id, f"{edu_case.cnr}|{o.order_no}|{o.order_date.isoformat()}"
    h = ds.login(api, "central_op")
    calls_before = _count(world, NapixCallLog)
    r = api.post("/admin/napix/sync-masters", headers=h)
    assert r.status_code == 202, r.text
    assert r.json() | {"queue_id": None} == {
        "kind": "masters",
        "ref": "all",
        "queue_id": None,
        "status": "pending",
        "priority": 10,
        "attempts": 0,
        "not_before": None,
        "lane": "request",
        "napix_enabled": False,
    }
    r = api.post("/admin/napix/refetch/day", json={"date": "2025-01-06"}, headers=h)
    assert r.status_code == 202 and (r.json()["ref"], r.json()["priority"]) == ("2025-01-06", 20)
    r = api.post("/admin/napix/refetch/case", json={"case": edu_case.ref_no.replace("/", "-")}, headers=h)
    assert r.status_code == 202 and (r.json()["ref"], r.json()["priority"]) == (edu_case.cnr, 30)
    r = api.post(
        "/admin/napix/refetch/order", json={"case": edu_case.cnr, "order_id": str(order_id)}, headers=h
    )
    assert r.status_code == 202, r.text
    assert (r.json()["kind"], r.json()["ref"], r.json()["status"]) == ("order_pdf", order_ref, "pending")
    assert gateway.seen == [] and gateway.token_calls == 0
    assert _count(world, NapixCallLog) == calls_before
    rows = _audits(world, "napix.refetch_requested")
    assert [(a.after["kind"], a.after["ref"], a.after["priority"]) for a in rows] == [
        ("causelist_day", "2025-01-06", 20),
        ("dossier", edu_case.cnr, 30),
        ("order_pdf", order_ref, 30),
    ]
    assert [a.case_id for a in rows] == [None, edu_case.id, edu_case.id]
    assert all(a.entity_type == "fetch_queue" and a.after["status_after"] == "pending" for a in rows)
    assert rows[0].after["status_before"] is None and rows[0].actor_office_code == "CENTRAL"
    (sync,) = _audits(world, "napix.masters_sync_requested")
    assert sync.entity_id == _row(world, FetchKind.MASTERS, "all").id
    with world.Session() as s:
        assert s.get(Order, order_id).download_status == DownloadStatus.PENDING
    assert _row(world, FetchKind.ORDER_PDF, order_ref).priority == 30


def test_refetch_day_rules(api, world):
    _put(world, FetchKind.CAUSELIST_DAY, "2025-01-06", FetchStatus.DONE, attempts=2)
    _put(world, FetchKind.CAUSELIST_DAY, "2025-01-07", FetchStatus.RUNNING, attempts=1)
    h = ds.login(api, "central_op")
    r = api.post("/admin/napix/refetch/day", json={"date": "2025-01-06"}, headers=h)
    assert r.status_code == 202
    assert (r.json()["status"], r.json()["attempts"], r.json()["priority"]) == ("pending", 0, 20)
    r = api.post("/admin/napix/refetch/day", json={"date": "2025-01-07"}, headers=h)
    assert r.status_code == 202 and r.json()["status"] == "running"
    (_a, running) = _audits(world, "napix.refetch_requested")
    assert (running.after["status_before"], running.after["status_after"]) == ("running", "running")
    tomorrow = today_ist() + timedelta(days=1)
    assert (
        api.post("/admin/napix/refetch/day", json={"date": tomorrow.isoformat()}, headers=h).status_code
        == 202
    )
    r = api.post(
        "/admin/napix/refetch/day", json={"date": (tomorrow + timedelta(days=1)).isoformat()}, headers=h
    )
    assert r.status_code == 400 and r.json()["detail"]["code"] == "date_in_future"
    assert len(_audits(world, "napix.refetch_requested")) == 3


def test_refetch_case_rules(api, world, edu_case):
    with world.Session() as s:
        provisional = make_case(s, case_no="WP(C)/555/2025")
        provisional.cnr, provisional.is_provisional = None, True
        nothing = make_case(s)
        nothing.cnr, nothing.case_no_text = None, None
        duplicate = make_case(s)
        duplicate.merged_into_case_id = edu_case.id
        s.commit()
        prov_id, nothing_id, dup_id = provisional.id, nothing.id, duplicate.id
    h = ds.login(api, "central_op")
    r = api.post("/admin/napix/refetch/case", json={"case": edu_case.cnr}, headers=h)
    assert r.status_code == 202 and r.json()["ref"] == edu_case.cnr
    r = api.post("/admin/napix/refetch/case", json={"case": str(prov_id)}, headers=h)
    assert r.status_code == 202 and r.json()["ref"] == "GAHC01|WP(C)/555/2025"
    r = api.post("/admin/napix/refetch/case", json={"case": str(dup_id)}, headers=h)
    assert r.status_code == 409 and r.json()["detail"] | {"message": ""} == {
        "code": "merged",
        "message": "",
        "ref_no": edu_case.ref_no,
    }
    r = api.post("/admin/napix/refetch/case", json={"case": str(nothing_id)}, headers=h)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "no_reference"
    r = api.post("/admin/napix/refetch/case", json={"case": "ASHC019999992099"}, headers=h)
    assert r.status_code == 404
    # a re-fetch grantee in a department membership: the EDU case is not visible to HEALTH
    _grant(world, "health_off", Permission.ADMIN_NAPIX_REFETCH)
    r = api.post(
        "/admin/napix/refetch/case", json={"case": edu_case.cnr}, headers=ds.login(api, "health_off")
    )
    assert r.status_code == 404 and r.json()["detail"]["code"] == "not_found"
    assert len(_audits(world, "napix.refetch_requested")) == 2


def test_refetch_order_rules(api, world, edu_case, tmp_path):
    with world.Session() as s:
        case = s.get(Case, edu_case.id)
        stored, _doc = ds.stored_order(s, api.store, case, sf.text_pdf(["order"]))
        other_case = make_case(s)
        foreign = ds.pending_order(s, other_case, order_no="3")
        missing = ds.pending_order(s, case, order_no="4")
        missing.download_status = DownloadStatus.NOT_AVAILABLE
        s.commit()
        ids = {"stored": stored.id, "foreign": foreign.id, "missing": missing.id}
    h = ds.login(api, "central_op")
    url = "/admin/napix/refetch/order"
    r = api.post(url, json={"case": edu_case.cnr, "order_id": str(ids["stored"])}, headers=h)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "already_stored"
    r = api.post(url, json={"case": edu_case.cnr, "order_id": str(ids["foreign"])}, headers=h)
    assert r.status_code == 404
    r = api.post(url, json={"case": edu_case.cnr, "order_id": str(ids["missing"])}, headers=h)
    assert r.status_code == 202 and r.json()["status"] == "pending"
    with world.Session() as s:
        assert s.get(Order, ids["missing"]).download_status == DownloadStatus.PENDING
    (audit,) = _audits(world, "napix.refetch_requested")
    assert audit.after["download_status_before"] == "not_available" and audit.case_id == edu_case.id
    with world.Session() as s:
        s.get(Case, edu_case.id).cnr = None
        s.commit()
    r = api.post(url, json={"case": str(edu_case.id), "order_id": str(ids["missing"])}, headers=h)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "no_reference"


def test_retry_item_and_retry_failed(api, world):
    failed = _put(
        world, FetchKind.DOSSIER, "ASHC010000012025", FetchStatus.FAILED, attempts=5, last_error="x"
    )
    skipped = _put(world, FetchKind.DOSSIER, "ASHC010000022025", FetchStatus.SKIPPED, attempts=1)
    pending = _put(world, FetchKind.DOSSIER, "ASHC010000032025", FetchStatus.PENDING)
    masters = _put(world, FetchKind.MASTERS, "all", FetchStatus.FAILED, attempts=5)
    for n in range(4, 7):
        _put(
            world, FetchKind.ORDER_PDF, f"ASHC010000{n:02d}2025|1|2025-01-10", FetchStatus.FAILED, attempts=5
        )
    h = ds.login(api, "central_op")
    for item in (failed, skipped):
        r = api.post(f"/admin/napix/queue/{item}/retry", headers=h)
        assert r.status_code == 200, r.text
        assert (r.json()["status"], r.json()["attempts"], r.json()["queue_id"]) == ("pending", 0, str(item))
    r = api.post(f"/admin/napix/queue/{pending}/retry", headers=h)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_retryable"
    assert api.post(f"/admin/napix/queue/{uuid.uuid4()}/retry", headers=h).status_code == 404
    # a re-fetch grantee without admin.masters_sync may not revive the masters row
    _grant(world, "health_off", Permission.ADMIN_NAPIX_REFETCH)
    ho = ds.login(api, "health_off")
    assert api.post(f"/admin/napix/queue/{masters}/retry", headers=ho).status_code == 403
    r = api.post("/admin/napix/queue/retry-failed", json={"kind": "masters"}, headers=ho)
    assert r.status_code == 403
    assert len(_audits(world, "napix.queue_retry")) == 2
    r = api.post("/admin/napix/queue/retry-failed", json={"kind": "order_pdf"}, headers=ho)
    assert r.status_code == 200 and r.json() == {"kind": "order_pdf", "retried": 3}
    with world.Session() as s:
        rows = s.scalars(sa.select(FetchQueueItem).where(FetchQueueItem.kind == FetchKind.ORDER_PDF)).all()
        assert {(r.status, r.attempts, r.last_error) for r in rows} == {(FetchStatus.PENDING, 0, None)}
    (bulk,) = _audits(world, "napix.queue_retry_failed")
    assert (
        bulk.after == {"kind": "order_pdf", "lane": None, "retried": 3} and bulk.actor_office_code == "HEALTH"
    )
    r = api.post(f"/admin/napix/queue/{masters}/retry", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "pending"


# ------------------------------------------------------------------------------------------------ the check


def test_health_check_one_call_logged_and_audited(api, world, gateway, switch_on):
    overview = sample("overview_2026-09-03.json")
    gateway.responses = [lambda p, q, r: gateway.envelope(overview)]
    gateway.rate_headers = {"X-RateLimit-Limit": "1000", "X-RateLimit-Remaining": "812"}
    h = ds.login(api, "central_op")
    r = api.post("/admin/napix/health/check", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["http_status"] == 200 and body["remaining"] == 812
    assert body["token_verified"] is True and body["error_family"] is None
    assert set(body) == {
        "ok",
        "called_at",
        "http_status",
        "napix_status",
        "error_family",
        "duration_ms",
        "token_verified",
        "remaining",
    }
    assert [x["path"] for x in gateway.seen] == ["overview/overview"]
    with world.Session() as s:
        logged = s.scalars(sa.select(NapixCallLog)).all()
    assert [(c.api, c.ok, c.rate_limit_remaining) for c in logged] == [("overview/overview", True, 812)]
    (audit,) = _audits(world, "napix.health_checked")
    assert audit.after["ok"] is True and audit.after["attempts"] == 1
    assert "payload" not in audit.after and "secret" not in repr(audit.after)
    # the NAPIX block shows the check; a second check within the minute is refused
    block = api.get("/admin/napix/health", headers=h).json()
    assert block["last_check"]["ok"] is True and block["hour"]["latest_remaining"] == 812
    again = api.post("/admin/napix/health/check", headers=h)
    assert again.status_code == 429 and again.json()["detail"]["code"] == "check_too_soon"


def test_health_check_refusals_make_no_call(api, world, gateway, monkeypatch):
    h = ds.login(api, "central_op")

    def nothing_written():
        return (_count(world, NapixCallLog), _count(world, AuditLog))

    before = nothing_written()
    r = api.post("/admin/napix/health/check", headers=h)  # the switch is off
    assert r.status_code == 409 and r.json()["detail"]["code"] == "napix_off"
    assert nothing_written() == before
    monkeypatch.setattr(Settings, "napix_configured", property(lambda self: True))
    with world.Session() as s:
        s.add(
            NapixCallLog(
                api="overview/overview",
                params_sha256="0" * 64,
                ok=True,
                called_at=datetime.now(UTC) - timedelta(seconds=10),
            )
        )
        s.commit()
    before = nothing_written()
    r = api.post("/admin/napix/health/check", headers=h)
    assert r.status_code == 429 and r.json()["detail"]["code"] == "check_too_soon"
    assert 1 <= int(r.headers["Retry-After"]) <= 50
    assert nothing_written() == before
    with world.Session() as s:
        s.execute(sa.text("SET session_replication_role = replica"))
        s.execute(sa.delete(NapixCallLog))
        s.add(
            NapixCallLog(
                api="hc-cnr-api/CNR",
                params_sha256="0" * 64,
                ok=True,
                rate_limit_remaining=10,
                called_at=datetime.now(UTC).replace(minute=0, second=0, microsecond=0),
            )
        )
        s.commit()
    before = nothing_written()
    r = api.post("/admin/napix/health/check", headers=h)
    assert r.status_code == 429 and r.json()["detail"]["code"] == "napix_budget"
    assert int(r.headers["Retry-After"]) >= 1
    assert nothing_written() == before
    assert gateway.seen == [] and gateway.token_calls == 0


def test_health_check_gateway_error_is_an_outcome(api, world, gateway, switch_on):
    gateway.responses = [lambda p, q, r: httpx.Response(503, text="busy")] * 3
    r = api.post("/admin/napix/health/check", headers=ds.login(api, "central_op"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False and body["error_family"] == "NapixUnavailable" and body["http_status"] == 503
    with world.Session() as s:
        logged = s.scalars(sa.select(NapixCallLog)).all()
    assert len(logged) == 3 and {(c.api, c.ok) for c in logged} == {("overview/overview", False)}
    (audit,) = _audits(world, "napix.health_checked")
    assert audit.after["ok"] is False and audit.after["attempts"] == 3


# ------------------------------------------------------------------------------------------------ the CLI


def test_cli_refetch_is_audited(world, edu_case, monkeypatch):
    from typer.testing import CliRunner

    from aslms.cli import pipeline

    @contextmanager
    def scope():
        s = world.Session()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    monkeypatch.setattr(pipeline, "session_scope", scope)
    monkeypatch.setattr(pipeline, "get_settings", lambda: Settings(_env_file=None, redis_url=None))
    import typer

    app = typer.Typer()
    app.command("refetch-date")(pipeline.refetch_date)
    app.command("refetch-case")(pipeline.refetch_case)
    runner = CliRunner()
    r = runner.invoke(app, ["refetch-date", "2025-01-06"])
    assert r.exit_code == 0, r.output
    r = runner.invoke(app, ["refetch-case", edu_case.cnr])
    assert r.exit_code == 0, r.output
    r = runner.invoke(app, ["refetch-case", "ASHC019999992099"])
    assert r.exit_code != 0
    rows = _audits(world, "napix.refetch_requested")
    assert [(a.after["kind"], a.after["ref"]) for a in rows] == [
        ("causelist_day", "2025-01-06"),
        ("dossier", edu_case.cnr),
    ]
    assert all(a.actor_user_id == world.users["root"].id for a in rows)
    assert _row(world, FetchKind.DOSSIER, edu_case.cnr).priority == 30
    assert date.fromisoformat(rows[0].after["ref"]) == date(2025, 1, 6)
