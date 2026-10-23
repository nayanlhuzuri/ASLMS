"""`/admin/data-load*` and the changed `/admin/napix/*` buttons (design `data-load-console`, decisions 9-12, 16, 17):
who reads and who acts, the start flow through the API, the single fetch with its warnings before any call, the
guard shared with the court search, visibility of results, details of found cases, the re-fetch warnings, the retry
by lane and the duplicates endpoints."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
import sqlalchemy as sa

from aslms.core.config import Settings
from aslms.domain.cases import Case
from aslms.domain.causelists import Causelist, ListSource, ListType
from aslms.domain.courts import CaseType, Court
from aslms.domain.documents import DownloadStatus, Order, OrderKind
from aslms.domain.events import AuditLog
from aslms.domain.ops import FetchKind, FetchLane, FetchQueueItem, FetchStatus, NapixCallLog
from aslms.domain.org import PermissionEffect, RolePermission
from aslms.domain.reference import Permission
from aslms.integration.napix.client import NapixClient
from aslms.integration.napix.crypto import NapixCrypto
from aslms.integration.napix.hc import NapixHighCourt
from aslms.services import access, case_dedupe
from aslms.services import ownership as own
from aslms.services.audit import Actor
from aslms.services.causelists import store_pdf
from aslms.services.refno import allocate_ref_no
from aslms.services.reporting_common import today_ist
from aslms.services.storage import LocalStore
from tests.db import docs_support as ds
from tests.db.conftest import router
from tests.db.world import make_case
from tests.unit.conftest import KEY, Gateway

CNR = "GAHC010129772026"
CNR2 = "GAHC010000452025"


@pytest.fixture()
def api(world, tmp_path):
    client = ds.make_api(world, tmp_path, napix_search_per_user_hour=3)
    yield client
    client.__exit__(None, None, None)


@pytest.fixture()
def gateway(api):
    """The scripted gateway (answers from the samples) behind the API's client factory."""
    gw = Gateway(NapixCrypto(KEY))
    gw.responses = [router(gw)] * 10_000

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


def _grant(world, key: str, perm: Permission = Permission.ADMIN_DATA_LOAD) -> None:
    with world.Session() as s:
        actor, root = world.actor(s, "root")
        access.set_override(s, actor, root, world.user(s, key), perm, PermissionEffect.GRANT, reason="test")
        s.commit()


def _audits(world, action: str) -> list[AuditLog]:
    with world.Session() as s:
        return list(
            s.scalars(sa.select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.created_at))
        )


def _held_case(world, cnr: str = CNR, **kw) -> Case:
    with world.Session() as s:
        case = make_case(s, cnr=cnr, **kw)
        case.last_full_refresh_at = datetime.now(UTC) - timedelta(days=3)
        s.commit()
        return case


def _err(r) -> dict:
    return r.json()["detail"]


# ------------------------------------------------------------------------------------------------ access


def test_permissions(api, world):
    with world.Session() as s:
        rows = s.scalars(
            sa.select(RolePermission).where(RolePermission.permission == Permission.ADMIN_DATA_LOAD)
        ).all()
        assert rows and not any(r.is_enabled for r in rows)  # no type holds it by default
    actions = [
        ("post", "/admin/data-load/preview", {"from": "2025-01-01", "to": "2025-01-02"}),
        ("post", "/admin/data-load/start", {"from": "2025-01-01", "to": "2025-01-02", "held": "skip"}),
        ("post", "/admin/data-load/pause", {"reason": "verification"}),
        ("post", "/admin/data-load/resume", {}),
        ("put", "/admin/data-load/order", {"load_order": "lists_first", "reason": "verification"}),
        ("post", "/admin/data-load/fetch", {"kind": "cnr", "cnr": CNR}),
        ("post", "/admin/data-load/fetch-details", {"cases": [CNR]}),
        ("post", "/admin/data-load/duplicates/scan", None),
    ]
    reads = ("/admin/data-load", "/admin/data-load/coverage", "/admin/data-load/duplicates")
    # a health reader reads but acts on nothing
    for key in ("oversight", "central_op"):
        h = ds.login(api, key)
        for path in reads:
            assert api.get(path, headers=h).status_code == 200, (key, path)
        for method, path, body in actions:
            r = getattr(api, method)(path, json=body, headers=h)
            assert r.status_code == 403, (key, path, r.text)
    # a login with neither gets nothing
    h = ds.login(api, "edu_off1")
    for path in reads:
        assert api.get(path, headers=h).status_code == 403
    # the super admin and a granted login act
    hr = ds.login(api, "root")
    assert api.post("/admin/data-load/pause", json={"reason": "verification"}, headers=hr).status_code == 200
    _grant(world, "central_op")
    h = ds.login(api, "central_op")
    r = api.post("/admin/data-load/resume", json={}, headers=h)
    assert r.status_code == 200 and r.json()["paused"] is False and r.json()["version"] == 2
    (resumed,) = _audits(world, "data_load.resumed")
    assert resumed.actor_office_code == "CENTRAL"


def test_progress_start_pause_order_flow(api, world):
    h = ds.login(api, "root")
    r = api.get("/admin/data-load", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["period"] is None and body["totals"] is None and body["napix_enabled"] is False
    assert body["settings"]["load_order"] == "cases_first" and body["estimate"]["reason"] is None
    assert set(body["allowance"]["used"]) == {"load", "discovery", "daily", "request", "outside_queue"}
    r = api.post("/admin/data-load/preview", json={"from": "2025-01-01", "to": "2025-01-31"}, headers=h)
    assert r.status_code == 200 and r.json()["not_queued"] == 31 and r.json()["calls_estimate"] is None
    r = api.post("/admin/data-load/start", json={"from": "2025-01-01", "to": "2025-01-31"}, headers=h)
    assert r.status_code == 202 and r.json()["queued"] == 31 and r.json()["masters_queued"] is True
    with world.Session() as s:
        s.execute(sa.text("UPDATE fetch_queue SET status = 'done' WHERE ref IN ('2025-01-02', '2025-01-03')"))
        s.commit()
    calls_before = _count_calls(world)
    queue_before = _queue_snapshot(world)
    r = api.post("/admin/data-load/start", json={"from": "2025-01-02", "to": "2025-01-03"}, headers=h)
    assert r.status_code == 409 and _err(r)["code"] == "already_held"
    assert _err(r)["held_with_lists"] == 2 and _err(r)["held_no_list"] == 0
    assert _count_calls(world) == calls_before and _queue_snapshot(world) == queue_before
    r = api.post(
        "/admin/data-load/start", json={"from": "2025-01-02", "to": "2025-01-03", "held": "skip"}, headers=h
    )
    assert r.status_code == 202 and r.json()["held_skipped"] == 2
    today = today_ist()  # the service's 'today' is the IST date; on a UTC runner after 18:30 they differ
    r = api.post(
        "/admin/data-load/start", json={"from": str(today), "to": str(today), "held": "skip"}, headers=h
    )
    assert r.status_code == 400 and _err(r)["code"] == "bad_range"
    r = api.post("/admin/data-load/pause", json={"reason": "verification"}, headers=h)
    assert r.status_code == 200 and r.json()["paused"] is True
    r = api.post("/admin/data-load/pause", json={"reason": "verification"}, headers=h)
    assert r.status_code == 409 and _err(r)["code"] == "no_change"
    r = api.put(
        "/admin/data-load/order",
        json={
            "load_order": "lists_first",
            "first_from": "2025-01-10",
            "first_to": "2025-01-12",
            "reason": "verify",
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["reprioritised"] == 29 and r.json()["settings"]["load_order"] == "lists_first"
    r = api.put(
        "/admin/data-load/order",
        json={
            "load_order": "lists_first",
            "first_from": "2024-01-10",
            "first_to": "2025-01-12",
            "reason": "verify",
        },
        headers=h,
    )
    assert r.status_code == 400 and _err(r)["code"] == "bad_period"
    body = api.get("/admin/data-load", headers=h).json()
    assert body["period"] == {"from": "2025-01-01", "to": "2025-01-31"}
    assert body["settings"]["paused"] is True and body["estimate"]["reason"] == "paused"
    assert {w["kind"]: w["pending"] for w in body["work_left"]}["causelist_day"] == 29
    r = api.get("/admin/data-load/coverage", headers=h)
    assert r.status_code == 200 and [m["month"] for m in r.json()["months"]] == ["2025-01"]
    assert r.json()["months"][0]["days"]["calendar"] == 31
    r = api.get("/admin/data-load/coverage?from=2025-01&to=2028-01", headers=h)
    assert r.status_code == 400 and _err(r)["code"] == "bad_period"
    with world.Session() as s:
        prio = dict(
            s.execute(
                sa.select(FetchQueueItem.ref, FetchQueueItem.priority).where(
                    FetchQueueItem.kind == FetchKind.CAUSELIST_DAY
                )
            ).all()
        )
    assert prio["2025-01-11"] == 41 and prio["2025-01-20"] == 44
    assert [a.action for a in _audits(world, "data_load.started")] == ["data_load.started"] * 2


def _count_calls(world) -> int:
    with world.Session() as s:
        return s.scalar(sa.select(sa.func.count()).select_from(NapixCallLog))


def _queue_snapshot(world):
    with world.Session() as s:
        return sorted(
            s.execute(sa.select(FetchQueueItem.kind, FetchQueueItem.ref, FetchQueueItem.status)).all()
        )


# ------------------------------------------------------------------------------------------------ single fetch


def test_fetch_cnr_already_held_then_force(api, world, gateway, switch_on):
    case = _held_case(world)
    h = ds.login(api, "root")
    r = api.post("/admin/data-load/fetch", json={"kind": "cnr", "cnr": CNR}, headers=h)
    assert r.status_code == 409 and _err(r)["code"] == "already_held"
    (held,) = _err(r)["cases"]
    assert (
        held["case"]["ref_no"] == case.ref_no
        and held["dossier_fetched_at"]
        and held["dossier_stale"] is False
    )
    assert gateway.seen == [] and _audits(world, "case.search_court") == []
    r = api.post("/admin/data-load/fetch", json={"kind": "cnr", "cnr": CNR, "force": True}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["source"] == "court" and r.json()["items"][0]["case"]["ref_no"] == case.ref_no
    assert [x["path"] for x in gateway.seen] == ["hc-cnr-api/CNR"]
    (audit,) = _audits(world, "case.search_court")
    assert (audit.after["via"], audit.after["force"], audit.after["warned"]) == ("data_load", True, True)
    with world.Session() as s:
        assert s.get(Case, case.id).last_full_refresh_at > case.last_full_refresh_at


def test_fetch_cnr_listed_without_details_fetches_directly(api, world, gateway, switch_on):
    with world.Session() as s:
        case = make_case(s, cnr=CNR2)
        s.commit()
    r = api.post("/admin/data-load/fetch", json={"kind": "cnr", "cnr": CNR2}, headers=ds.login(api, "root"))
    assert r.status_code == 200, r.text
    assert len(gateway.seen) == 1 and r.json()["items"][0]["case"]["ref_no"] == case.ref_no
    (audit,) = _audits(world, "case.search_court")
    assert audit.after["warned"] is False and audit.after["force"] is False


def test_fetch_case_number_held_and_party_searched_before(api, world, gateway, switch_on):
    with world.Session() as s:
        court = s.scalar(sa.select(Court).where(Court.est_code == "GAHC01"))
        ct = CaseType(court_id=court.id, case_type_code=111, type_name="WP(C)", short_name="WP(C)")
        s.add(ct)
        s.flush()
        case = make_case(s, cnr=CNR, case_no="WP(C)/3600/2026", pet="RAMEN DAS")
        case.case_type_id, case.reg_no, case.reg_year = ct.id, 3600, 2026
        case.last_full_refresh_at = datetime.now(UTC)
        s.add(
            AuditLog(
                action="case.search_court",
                entity_type="napix_search",
                actor_name="someone",
                after={
                    "kind": "party",
                    "request": {"name": "ramen das", "reg_year": 2026, "pend_disp": "P"},
                    "results": 4,
                    "outcome": "ok",
                },
            )
        )
        s.commit()
    h = ds.login(api, "root")
    r = api.post(
        "/admin/data-load/fetch",
        json={"kind": "case_number", "case_type": "WP(C)", "reg_no": 3600, "reg_year": 2026},
        headers=h,
    )
    assert r.status_code == 409 and _err(r)["code"] == "already_held"
    assert _err(r)["cases"][0]["case"]["ref_no"] == case.ref_no
    r = api.post(
        "/admin/data-load/fetch", json={"kind": "party", "name": "RAMEN DAS", "reg_year": 2026}, headers=h
    )
    assert r.status_code == 409 and _err(r)["code"] == "searched_before"
    assert _err(r)["stored"] == 4 and _err(r)["last_searched_at"]
    assert gateway.seen == []
    r = api.post(
        "/admin/data-load/fetch",
        json={"kind": "party", "name": "RAMEN DAS", "reg_year": 2026, "force": True},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert [x["path"] for x in gateway.seen] == ["hc-party-name-api/partyname"]
    # another year was never searched: no warning
    gateway.seen.clear()
    r = api.post(
        "/admin/data-load/fetch", json={"kind": "party", "name": "RAMEN DAS", "reg_year": 2024}, headers=h
    )
    assert r.status_code == 200 and len(gateway.seen) == 1


def test_fetch_guard_shared_with_court_search(api, world, gateway, monkeypatch):
    _grant(world, "central_op")
    h = ds.login(api, "central_op")
    r = api.post("/admin/data-load/fetch", json={"kind": "cnr", "cnr": CNR}, headers=h)
    assert r.status_code == 503 and _err(r)["code"] == "napix_off" and gateway.seen == []
    monkeypatch.setattr(Settings, "napix_configured", property(lambda self: True))
    assert api.post("/cases/search-court", json={"kind": "cnr", "cnr": CNR}, headers=h).status_code == 200
    r = api.post("/admin/data-load/fetch", json={"kind": "cnr", "cnr": CNR2}, headers=h)
    assert r.status_code == 200, r.text
    assert (
        api.post(
            "/cases/search-court", json={"kind": "cnr", "cnr": "GAHC010000462025"}, headers=h
        ).status_code
        == 200
    )
    calls = len(gateway.seen)
    r = api.post("/admin/data-load/fetch", json={"kind": "cnr", "cnr": "GAHC010000472025"}, headers=h)
    assert r.status_code == 429 and _err(r)["code"] == "search_limit" and len(gateway.seen) == calls


def test_fetch_results_respect_visibility(api, world, gateway, switch_on):
    with world.Session() as s:
        case = make_case(s, cnr=CNR)
        actor, admin = world.actor(s, "edu_admin")
        own.claim(s, actor, admin, case)
        s.commit()
    _grant(world, "health_admin")
    r = api.post(
        "/admin/data-load/fetch", json={"kind": "cnr", "cnr": CNR}, headers=ds.login(api, "health_admin")
    )
    assert r.status_code == 200, r.text
    (item,) = r.json()["items"]
    assert item["visible"] is False and item["case"]["ref_no"] == case.ref_no
    r = api.get(f"/cases/{case.ref_no}", headers=ds.login(api, "health_admin"))
    assert r.status_code in (403, 404)


def test_fetch_details_queues_request_lane(api, world):
    with world.Session() as s:
        make_case(s, cnr="GAHC010000482025")
        held = make_case(s, cnr="GAHC010000492025")
        held.last_full_refresh_at = datetime.now(UTC)
        holder = make_case(s, cnr="GAHC010000502025", case_no="WA/50/2025")
        court = s.scalar(sa.select(Court).where(Court.est_code == "GAHC01"))
        merged = Case(
            court_id=court.id,
            case_no_text="WA/50/2025",
            ref_no=allocate_ref_no(s, "GOA", "CASE"),
            is_provisional=True,
        )
        s.add(merged)
        s.flush()
        merged_ref, holder_ref = merged.ref_no, holder.ref_no
        case_dedupe.merge_provisional(s, merged, holder, Actor.system("test"))
        s.commit()
    h = ds.login(api, "root")
    bare_cnr, held_cnr = "GAHC010000482025", "GAHC010000492025"
    refs = [bare_cnr, held_cnr, merged_ref, "GAHC019999992025"]
    r = api.post("/admin/data-load/fetch-details", json={"cases": refs}, headers=h)
    assert r.status_code == 200, r.text
    states = {i["ref"]: i for i in r.json()["items"]}
    assert states[bare_cnr]["state"] == "queued"
    assert states[bare_cnr]["queue"]["lane"] == "request" and states[bare_cnr]["queue"]["priority"] == 30
    assert states[held_cnr]["state"] == "already_held" and states[held_cnr]["queue"] is None
    assert states[merged_ref]["state"] == "merged" and states[merged_ref]["merged_into_ref_no"] == holder_ref
    assert states["GAHC019999992025"]["state"] == "not_found" and states["GAHC019999992025"]["case"] is None
    (audit,) = _audits(world, "data_load.details_requested")
    assert audit.after["count"] == 4 and audit.after["queued"] == 1
    r = api.post("/admin/data-load/fetch-details", json={"cases": [held_cnr], "force": True}, headers=h)
    assert r.json()["items"][0]["state"] == "queued"
    with world.Session() as s:
        row = s.scalar(sa.select(FetchQueueItem).where(FetchQueueItem.ref == held_cnr))
        assert (row.lane, row.priority, row.status) == (FetchLane.REQUEST, 30, FetchStatus.PENDING)
    assert api.post("/admin/data-load/fetch-details", json={"cases": []}, headers=h).status_code == 422


# ------------------------------------------------------------------------------------------------ the buttons


def test_refetch_day_and_case_warn_then_force(api, world, tmp_path):
    with world.Session() as s:
        court = s.scalar(sa.select(Court).where(Court.est_code == "GAHC01"))
        doc, _ = store_pdf(
            s, LocalStore(str(tmp_path / "s")), b"%PDF-1.4 x", doc_date=date(2025, 1, 6), description="t"
        )
        s.add(
            Causelist(
                court_id=court.id,
                list_date=date(2025, 1, 6),
                list_type=ListType.DAILY,
                source=ListSource.NAPIX,
                document_id=doc.id,
            )
        )
        for ref, st in (
            ("2025-01-06", FetchStatus.DONE),
            ("2025-01-05", FetchStatus.SKIPPED),
            ("2025-01-07", FetchStatus.DONE),
        ):
            s.add(
                FetchQueueItem(
                    kind=FetchKind.CAUSELIST_DAY, ref=ref, status=st, priority=46, lane=FetchLane.LOAD
                )
            )
        case = make_case(s, cnr=CNR)
        case.last_full_refresh_at = datetime.now(UTC)
        order = Order(
            case_id=case.id,
            order_no="1",
            order_date=date(2025, 1, 6),
            kind=OrderKind.INTERIM,
            document_id=doc.id,
            download_status=DownloadStatus.STORED,
        )
        s.add(order)
        s.commit()
    h = ds.login(api, "central_op")
    for day, lists in (("2025-01-06", 1), ("2025-01-05", 0)):
        r = api.post("/admin/napix/refetch/day", json={"date": day}, headers=h)
        assert r.status_code == 409 and _err(r)["code"] == "already_held", r.text
        assert _err(r)["lists_stored"] == lists
    assert _audits(world, "napix.refetch_requested") == []
    r = api.post(
        "/admin/napix/refetch/day", json={"date": "2025-01-07"}, headers=h
    )  # done but nothing stored
    assert r.status_code == 202 and r.json()["lane"] == "request"
    r = api.post("/admin/napix/refetch/day", json={"date": "2025-01-06", "force": True}, headers=h)
    assert r.status_code == 202 and r.json()["status"] == "pending"
    r = api.post("/admin/napix/refetch/case", json={"case": CNR}, headers=h)
    assert r.status_code == 409 and _err(r)["code"] == "already_held" and _err(r)["dossier_fetched_at"]
    r = api.post("/admin/napix/refetch/case", json={"case": CNR, "force": True}, headers=h)
    assert r.status_code == 202 and r.json()["lane"] == "request" and r.json()["priority"] == 30
    r = api.post("/admin/napix/refetch/order", json={"case": CNR, "order_id": str(order.id)}, headers=h)
    assert r.status_code == 409 and _err(r)["code"] == "already_stored"
    assert len(_audits(world, "napix.refetch_requested")) == 3


def test_retry_failed_by_lane(api, world):
    with world.Session() as s:
        for ref, lane in (("GAHC010000012025", FetchLane.LOAD), ("GAHC010000022025", FetchLane.DAILY)):
            s.add(
                FetchQueueItem(
                    kind=FetchKind.DOSSIER,
                    ref=ref,
                    status=FetchStatus.FAILED,
                    attempts=5,
                    priority=44,
                    lane=lane,
                )
            )
        s.commit()
    h = ds.login(api, "central_op")
    r = api.post("/admin/napix/queue/retry-failed", json={"kind": "dossier", "lane": "load"}, headers=h)
    assert r.status_code == 200 and r.json()["retried"] == 1
    with world.Session() as s:
        states = dict(s.execute(sa.select(FetchQueueItem.ref, FetchQueueItem.status)).all())
    assert states == {"GAHC010000012025": FetchStatus.PENDING, "GAHC010000022025": FetchStatus.FAILED}
    (audit,) = _audits(world, "napix.queue_retry_failed")
    assert audit.after == {"kind": "dossier", "lane": "load", "retried": 1}
    r = api.get("/admin/napix/queue?lane=load", headers=h)
    assert r.status_code == 200 and r.json()["total"] == 1 and r.json()["items"][0]["lane"] == "load"


def test_duplicates_endpoints_and_scan(api, world):
    with world.Session() as s:
        holder = make_case(s, cnr="GAHC010000612025", case_no="WP(C)/61/2025")
        court = s.scalar(sa.select(Court).where(Court.est_code == "GAHC01"))
        s.add(
            Case(
                court_id=court.id,
                case_no_text="WP(C)/61/2025",
                ref_no=allocate_ref_no(s, "GOA", "CASE"),
                is_provisional=True,
            )
        )
        make_case(s, cnr="GAHC010000622025", case_no="WA/62/2025")
        make_case(s, cnr="GAHC010000632025", case_no="WA/62/2025")
        s.commit()
    h = ds.login(api, "root")
    r = api.post("/admin/data-load/duplicates/scan", headers=h)
    assert r.status_code == 200 and r.json() == {"merged": 1, "needs_review": 0, "court_linked": 1}
    (audit,) = _audits(world, "data_load.dedupe_scan")
    assert audit.after["merged"] == 1 and audit.after["dry_run"] is False
    merged = api.get("/admin/data-load/duplicates?kind=merged", headers=h).json()
    assert merged["total"] == 1 and merged["items"][0]["other"]["ref_no"] == holder.ref_no
    court_dups = api.get("/admin/data-load/duplicates?kind=court", headers=h).json()
    assert court_dups["total"] == 1 and court_dups["items"][0]["case"]["cnr"] == "GAHC010000632025"
    assert set(court_dups["items"][0]["case"]) == {"id", "ref_no", "cnr", "case_no_text"}
    review = api.get("/admin/data-load/duplicates?kind=review", headers=ds.login(api, "oversight")).json()
    assert review == {"total": 0, "items": []}
    assert api.get("/admin/data-load/duplicates?kind=other", headers=h).status_code == 422


def test_endpoints_refuse_unauthenticated_and_disabled_users(api, world):
    from aslms.domain.org import User

    calls = (
        ("get", "/admin/data-load"),
        ("get", "/admin/data-load/coverage"),
        ("get", "/admin/data-load/duplicates"),
        ("post", "/admin/data-load/preview"),
        ("post", "/admin/data-load/pause"),
        ("post", "/admin/data-load/resume"),
        ("put", "/admin/data-load/order"),
        ("post", "/admin/data-load/fetch"),
        ("post", "/admin/data-load/fetch-details"),
        ("post", "/admin/data-load/duplicates/scan"),
    )
    for method, path in calls:
        assert getattr(api, method)(path).status_code == 401, path
        assert getattr(api, method)(path, headers={"Authorization": "Bearer nope"}).status_code == 401, path
    headers = ds.login(api, "root")
    assert api.get("/admin/data-load", headers=headers).status_code == 200
    with world.Session() as s:
        s.execute(sa.update(User).where(User.id == world.users["root"].id).values(is_active=False))
        s.commit()
    for method, path in calls:
        assert getattr(api, method)(path, headers=headers).status_code == 401, path


# ------------------------------------------------------------------------------------------------ recorded apart


def test_fetch_call_rows_survive_an_unexpected_error(api, world, gateway, switch_on, monkeypatch):
    """Design api-health-checker-followups, decision 11: the call rows and the verbatim response are committed apart;
    the case data and the audit row of the failed request are not."""
    from aslms.services import court_search

    def broken(*args, **kwargs):
        raise RuntimeError("apply defect")

    monkeypatch.setattr(court_search, "apply_dossier", broken)
    with pytest.raises(RuntimeError, match="apply defect"):  # the request answers 500
        api.post("/admin/data-load/fetch", json={"kind": "cnr", "cnr": CNR2}, headers=ds.login(api, "root"))
    assert [x["path"] for x in gateway.seen] == ["hc-cnr-api/CNR"]
    with world.Session() as s:
        root_id = world.user(s, "root").id
        calls = s.scalars(sa.select(NapixCallLog)).all()
        assert [(c.api, c.user_id) for c in calls] == [("hc-cnr-api/CNR", root_id)]
        assert s.scalar(sa.text("select count(*) from napix_responses")) == 1
        assert s.scalar(sa.select(sa.func.count()).select_from(Case).where(Case.cnr == CNR2)) == 0
    assert _audits(world, "case.search_court") == []


def test_fetch_details_makes_no_court_call(api, world, gateway, switch_on):
    """`fetch-details` only queues dossier rows for the worker (which commits its own rows): no request-time call,
    so it has no call rows to lose (design api-health-checker-followups, decision 11)."""
    with world.Session() as s:
        make_case(s, cnr=CNR2)
        s.commit()
    r = api.post("/admin/data-load/fetch-details", json={"cases": [CNR2]}, headers=ds.login(api, "root"))
    assert r.status_code == 200 and r.json()["items"][0]["state"] == "queued"
    assert gateway.seen == [] and gateway.token_calls == 0
    with world.Session() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(NapixCallLog)) == 0
