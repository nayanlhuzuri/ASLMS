"""A Collect Now request's items are exactly the rows of its own run and what that run spawned (row 174 review,
design `data-collection-redesign`, decision 32): the rows carry the request's id (`fetch_queue.result.request_ids`),
so later work by anyone else on the same cases (a claim's court refresh, Fetch Details, a person's court search, a
One Case request) never reopens a finished request, never makes it the bulk request using the allowance and never
blames it for a refused court search. Also: Stop reaches what a running row spawns (A2), the worker's wake check asks
only for the kinds a pass can claim (A3), retries keep a bulk request open for the one-at-a-time rule and Stop (A4),
and a provisional reference matches its own establishment only (A6)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from aslms.cli.pipeline import has_now_check
from aslms.core.config import Settings
from aslms.domain.cases import Case, FirstSeenSource
from aslms.domain.courts import Court
from aslms.domain.documents import DownloadStatus, Order, OrderKind
from aslms.domain.ops import FetchKind, FetchLane, FetchQueueItem, FetchStatus
from aslms.services import collect, court_search, ownership, queue
from aslms.services.load_policy import NOW_BULK, NOW_ONE, REQUEST_ORDER_PDF, QueueOrigin
from aslms.services.napix_store import NapixRecorder
from aslms.services.refno import allocate_case_ref_no
from aslms.services.reporting_common import today_ist
from aslms.services.runner import Claimed, QueueRunner, RunReport, claim_kinds
from aslms.services.storage import LocalStore
from tests.db import docs_support as ds
from tests.db.world import make_case

CNR_A = "GAHC010000312025"
CNR_B = "GAHC010000322025"
TODAY = today_ist()


@pytest.fixture()
def api(world, tmp_path):
    client = ds.make_api(world, tmp_path)
    yield client
    client.__exit__(None, None, None)


def _runner(world, hc, tmp_path, recorder) -> QueueRunner:
    settings = Settings(
        _env_file=None, storage_dir=str(tmp_path / "store"), causelist_dir=str(tmp_path / "lists")
    )
    return QueueRunner(
        world.Session,
        hc,
        settings=settings,
        store=LocalStore(settings.storage_dir),
        causelist_dir=tmp_path / "lists",
        recorder=recorder,
    )


def _run_dossiers(world, napix, tmp_path, n: int) -> RunReport:
    """The worker: `n` dossier rows through the scripted gateway, each spawning its missing order PDFs."""
    _gw, client, hc = napix
    recorder = NapixRecorder()
    client.on_call = recorder.on_call

    async def go():
        async with client:
            return await _runner(world, hc, tmp_path, recorder).run(max_items=n, kinds=[FetchKind.DOSSIER])

    rep = asyncio.run(go())
    assert rep.done == n, rep.items
    return rep


def _end_order_pdfs(world) -> None:
    """The request's order PDFs end without a court call: the first not available (skipped), the others done."""
    with world.Session() as s:
        first = True
        while (item := queue.claim(s, [FetchKind.ORDER_PDF], max_priority=NOW_BULK)) is not None:
            queue.complete(s, item, skipped=first)
            first = False
        s.commit()


def _tags(world, kind: FetchKind) -> dict[str, list[str]]:
    with world.Session() as s:
        rows = s.scalars(sa.select(FetchQueueItem).where(FetchQueueItem.kind == kind)).all()
        return {r.ref: sorted((r.result or {}).get("request_ids") or []) for r in rows}


def _detail(api, h, rid: str) -> dict:
    r = api.get(f"/admin/data-load/requests/{rid}", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _finished_bulk(api, world, napix, tmp_path, h) -> str:
    """A bulk request "List of 2 Cases" carried out: both dossiers fetched, their six order PDFs ended. Then a day
    passes: the details are two days old and the court has published a new order of case A."""
    with world.Session() as s:
        make_case(s, cnr=CNR_A)
        make_case(s, cnr=CNR_B)
        s.commit()
    r = api.post("/admin/data-load/collect", json={"kind": "list", "lines": [CNR_A, CNR_B]}, headers=h)
    assert r.status_code == 202, r.text
    rid = r.json()["request_id"]
    _run_dossiers(world, napix, tmp_path, 2)
    tags = _tags(world, FetchKind.ORDER_PDF)
    assert len(tags) == 6 and set(map(tuple, tags.values())) == {(rid,)}  # spawned with the request's id
    _end_order_pdfs(world)
    d = _detail(api, h, rid)
    assert d["finished"] and not d["using_everything"] and d["total"] == 8
    assert d["counts"]["done"] == 7 and d["counts"]["not_found"] == 1
    with world.Session() as s:
        case = s.scalar(sa.select(Case).where(Case.cnr == CNR_A))
        case.last_full_refresh_at = datetime.now(UTC) - timedelta(days=2)
        s.add(
            Order(
                case_id=case.id,
                order_no="99",
                order_date=TODAY,
                kind=OrderKind.INTERIM,
                download_status=DownloadStatus.PENDING,
            )
        )
        s.commit()
    return rid


def _assert_still_finished(api, world, h, rid: str) -> None:
    d = _detail(api, h, rid)
    assert d["finished"] and not d["using_everything"], d["counts"]
    # its two dossiers and five PDFs; the PDF not available before, queued again by the later work, is that work's
    # now and has left the request (its outcome is not kept apart from the later run's)
    assert d["total"] == 7 and d["counts"]["waiting"] == 0 and d["counts"]["fetching"] == 0
    listed = {i["request_id"]: i for i in api.get("/admin/data-load/requests", headers=h).json()["items"]}
    assert listed[rid]["finished"] and not listed[rid]["using_everything"]
    with world.Session() as s:
        assert collect.active_bulk(s) is None
        assert (
            collect.bulk_message(s, Settings(_env_file=None)) is None
        )  # a refused court search blames no one
    assert api.get("/admin/data-load/overview", headers=h).json()["bulk"] is None
    r = api.post("/admin/data-load/collect", json={"kind": "list", "lines": ["GAHC019999972025"]}, headers=h)
    assert r.status_code == 202, r.text  # another bulk request may start


def _later_pdfs(world, rid: str) -> dict[str, FetchQueueItem]:
    """Case A's order PDFs pending after the later work: the new order (a new row) and the one not available before
    (revived); none carries the finished request's id."""
    with world.Session() as s:
        rows = s.scalars(
            sa.select(FetchQueueItem).where(
                FetchQueueItem.kind == FetchKind.ORDER_PDF,
                FetchQueueItem.status == FetchStatus.PENDING,
            )
        ).all()
        s.expunge_all()
    pending = {r.ref: r for r in rows if r.ref.startswith(CNR_A)}
    assert any(ref.split("|")[1] == "99" for ref in pending), pending
    assert all(rid not in ((r.result or {}).get("request_ids") or []) for r in pending.values())
    assert {r.lane for r in pending.values()} == {FetchLane.REQUEST}
    return pending


# ------------------------------------------------------------------------------------------------ the blocking finding


def test_a_claims_court_refresh_never_reopens_a_finished_bulk_request(api, world, napix, tmp_path):
    h = ds.login(api, "root")
    rid = _finished_bulk(api, world, napix, tmp_path, h)
    with world.Session() as s:
        case = s.scalar(sa.select(Case).where(Case.cnr == CNR_A))
        assert ownership._queue_court_refresh(s, case, world.user(s, "edu_off1")) == "queued"
        s.commit()
    _run_dossiers(world, napix, tmp_path, 1)  # the refresh at 30 spawns the case's missing PDFs at 40
    pending = _later_pdfs(world, rid)
    assert {r.priority for r in pending.values()} == {REQUEST_ORDER_PDF}
    assert all(not (r.result or {}).get("request_ids") for r in pending.values())
    _assert_still_finished(api, world, h, rid)


def test_fetch_details_on_one_of_its_cases_never_reopens_it(api, world, napix, tmp_path):
    h = ds.login(api, "root")
    rid = _finished_bulk(api, world, napix, tmp_path, h)
    with world.Session() as s:
        ref = s.scalar(sa.select(Case.ref_no).where(Case.cnr == CNR_A))
    r = api.post("/admin/data-load/fetch-details", json={"cases": [ref], "force": True}, headers=h)
    assert r.status_code == 200, r.text
    details = next(
        i for i in api.get("/admin/data-load/requests", headers=h).json()["items"] if i["kind"] == "details"
    )
    _run_dossiers(world, napix, tmp_path, 1)
    pending = _later_pdfs(world, rid)
    # the PDFs are Fetch Details' own items: its run spawned them
    assert all((r.result or {}).get("request_ids") == [details["request_id"]] for r in pending.values())
    d = _detail(api, h, details["request_id"])
    assert not d["finished"] and d["counts"]["waiting"] == len(pending) and d["total"] == 1 + len(pending)
    _assert_still_finished(api, world, h, rid)


def test_a_persons_court_search_never_reopens_it(api, world, napix, tmp_path):
    h = ds.login(api, "root")
    rid = _finished_bulk(api, world, napix, tmp_path, h)
    _gw, client, hc = napix

    async def search():
        async with client:
            with world.Session() as s:
                court = s.scalar(sa.select(Court).where(Court.est_code == "GAHC01"))
                origin = court_search.request_origin(world.user(s, "edu_off1"))
                await court_search.fetch_dossier(
                    s, hc, court, CNR_A, source=FirstSeenSource.SEARCH, origin=origin
                )
                s.commit()

    asyncio.run(search())
    _later_pdfs(world, rid)
    _assert_still_finished(api, world, h, rid)


def test_a_one_case_request_on_one_of_its_cases_never_reopens_it(api, world, napix, tmp_path):
    h = ds.login(api, "root")
    rid = _finished_bulk(api, world, napix, tmp_path, h)
    r = api.post("/admin/data-load/collect", json={"kind": "cases", "refs": [CNR_A]}, headers=h)
    assert r.status_code == 202, r.text
    one = r.json()["request_id"]
    _run_dossiers(world, napix, tmp_path, 1)
    pending = _later_pdfs(world, rid)
    assert {r.priority for r in pending.values()} == {NOW_ONE}
    assert all((r.result or {}).get("request_ids") == [one] for r in pending.values())
    d = _detail(api, h, one)
    assert not d["finished"] and not d["bulk"] and d["total"] == 1 + len(pending)
    _assert_still_finished(api, world, h, rid)


def test_request_ids_on_the_queue_row(world):
    """`enqueue` sets the ids on an inserted or revived row, adds them to a pending one and clears them when system
    work revives the row; `complete` keeps them next to the result and `fail` leaves them."""
    a, b = "0190a000-0000-7000-8000-00000000000a", "0190a000-0000-7000-8000-00000000000b"
    ref = f"{CNR_A}|1|2025-01-06"

    def tags(s) -> list[str]:
        return sorted(queue.request_tags(s, queue.get_state(s, FetchKind.ORDER_PDF, ref).id))

    with world.Session() as s:
        queue.enqueue(s, FetchKind.ORDER_PDF, ref, NOW_BULK, lane=FetchLane.REQUEST, request_ids=[a])
        assert tags(s) == [a]
        queue.enqueue(s, FetchKind.ORDER_PDF, ref, 60)  # system work on a pending row keeps them
        queue.enqueue(s, FetchKind.ORDER_PDF, ref, NOW_ONE, lane=FetchLane.REQUEST, request_ids=[b, a])
        assert tags(s) == [a, b]
        item = queue.claim(s, [FetchKind.ORDER_PDF])
        queue.fail(s, item, "court busy")
        assert tags(s) == [a, b]  # its retry is still theirs
        s.execute(sa.text("UPDATE fetch_queue SET not_before = NULL"))
        item = queue.claim(s, [FetchKind.ORDER_PDF])
        queue.complete(s, item, {"stored": True})
        row = queue.get_state(s, FetchKind.ORDER_PDF, ref)
        assert row.result["stored"] is True and sorted(row.result["request_ids"]) == [a, b]
        queue.enqueue(s, FetchKind.ORDER_PDF, ref, 60, requeue=True)  # later system work: none of theirs
        assert tags(s) == [] and queue.get_state(s, FetchKind.ORDER_PDF, ref).result == {"stored": True}
        queue.enqueue(s, FetchKind.ORDER_PDF, ref, 40, lane=FetchLane.REQUEST)
        item = queue.claim(s, [FetchKind.ORDER_PDF])
        queue.complete(s, item, {"x": 1}, skipped=True)
        queue.enqueue(s, FetchKind.ORDER_PDF, ref, NOW_ONE, lane=FetchLane.REQUEST, request_ids=[b])
        assert tags(s) == [b]  # a revived row takes exactly the caller's
        s.rollback()


# ------------------------------------------------------------------------------------------------ A2: Stop reaches spawns


def test_stop_reaches_the_order_pdfs_a_running_dossier_spawns(api, world, napix, tmp_path):
    with world.Session() as s:
        make_case(s, cnr=CNR_A)
        make_case(s, cnr=CNR_B)
        s.commit()
    h = ds.login(api, "root")
    rid = api.post(
        "/admin/data-load/collect", json={"kind": "list", "lines": [CNR_A, CNR_B]}, headers=h
    ).json()["request_id"]
    with world.Session() as s:
        claimed = Claimed.of(queue.claim(s, [FetchKind.DOSSIER], max_priority=NOW_BULK))
        s.commit()
    assert claimed.priority == NOW_BULK
    r = api.post(f"/admin/data-load/requests/{rid}/stop", headers=h)
    assert r.status_code == 200 and r.json()["moved"] == 1, r.text
    with world.Session() as s:
        row = s.get(FetchQueueItem, claimed.id)
        assert (row.status, row.priority) == (FetchStatus.RUNNING, 30)  # its run goes on, at the normal turn
    # the worker finishes the run it claimed at 5: what it spawns reads the row's priority now
    _gw, client, hc = napix
    recorder = NapixRecorder()
    client.on_call = recorder.on_call

    async def finish():
        async with client:
            runner = _runner(world, hc, tmp_path, recorder)
            return await runner._process(
                claimed.id,
                claimed.kind,
                claimed.ref,
                RunReport(),
                lane=claimed.lane,
                requested_by=claimed.requested_by,
                priority=claimed.priority,
            )

    assert asyncio.run(finish()) is None
    with world.Session() as s:
        pdfs = s.scalars(sa.select(FetchQueueItem).where(FetchQueueItem.kind == FetchKind.ORDER_PDF)).all()
        assert len(pdfs) == 3
        assert {(p.priority, p.lane) for p in pdfs} == {(REQUEST_ORDER_PDF, FetchLane.REQUEST)}
        assert not queue.has_now(s)  # nothing runs outside the reserves after Stop
    d = _detail(api, h, rid)
    assert d["stopped"] and d["total"] == 2 + 3  # still the request's items, in the normal turn


# ------------------------------------------------------------------------------------------------ A3: the wake check


def test_wake_check_asks_only_for_the_kinds_a_pass_can_claim(clean_db, monkeypatch):
    off = Settings(_env_file=None)
    assert not off.napix_configured
    assert claim_kinds(off, None) == [FetchKind.CAUSELIST_DAY]
    assert claim_kinds(off, [FetchKind.MASTERS]) == [FetchKind.MASTERS]
    with clean_db() as s:
        queue.enqueue(s, FetchKind.DOSSIER, CNR_A, NOW_BULK, lane=FetchLane.REQUEST)
        s.commit()
    # with the gateway off the pass claims only cause-list days: a "now" dossier must not wake it every 2 s
    assert has_now_check(clean_db)() is True
    assert has_now_check(clean_db, claim_kinds(off, None))() is False
    with clean_db() as s:
        queue.enqueue(s, FetchKind.CAUSELIST_DAY, "2025-01-06", NOW_ONE, lane=FetchLane.REQUEST)
        s.commit()
    assert has_now_check(clean_db, claim_kinds(off, None))() is True
    monkeypatch.setattr(Settings, "napix_configured", property(lambda self: True))
    assert claim_kinds(Settings(_env_file=None), None) is None


# ------------------------------------------------------------------------------------------------ A4: retries stay open


def test_a_bulk_request_with_only_retries_left_still_holds_the_allowance(api, world):
    with world.Session() as s:
        make_case(s, cnr=CNR_A)
        s.commit()
    h = ds.login(api, "root")
    rid = api.post("/admin/data-load/collect", json={"kind": "list", "lines": [CNR_A]}, headers=h).json()[
        "request_id"
    ]
    with world.Session() as s:
        item = queue.claim(s, [FetchKind.DOSSIER], max_priority=NOW_BULK)
        queue.fail(s, item, "court busy")  # waits 10 minutes for its retry
        s.commit()
    d = _detail(api, h, rid)
    assert d["finished"] and d["counts"]["waiting_retry"] == 1  # the result shows, with the retry time
    assert d["using_everything"] and d["expected_end"] is not None
    with world.Session() as s:
        assert str(collect.active_bulk(s).id) == rid
    r = api.post("/admin/data-load/collect", json={"kind": "list", "lines": ["GAHC019999972025"]}, headers=h)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "bulk_running"
    r = api.post(f"/admin/data-load/requests/{rid}/stop", headers=h)
    assert r.status_code == 200 and r.json()["moved"] == 1, r.text
    with world.Session() as s:
        row = queue.get_state(s, FetchKind.DOSSIER, CNR_A)
        assert (row.status, row.priority) == (FetchStatus.PENDING, 30)
        assert collect.active_bulk(s) is None


# ------------------------------------------------------------------------------------------------ A6: the establishment


def test_a_provisional_reference_matches_its_own_establishment_only(api, world):
    with world.Session() as s:
        principal = s.scalar(sa.select(Court).where(Court.est_code == "GAHC01"))
        kohima = s.scalar(sa.select(Court).where(Court.est_code == "GAHC02"))
        provisional = Case(
            court_id=principal.id,
            case_no_text="WA/77/2025",
            ref_no=allocate_case_ref_no(s, principal),
            is_provisional=True,
        )
        elsewhere = Case(
            court_id=kohima.id,
            cnr="GAHC020000772025",
            case_no_text="WA/77/2025",
            ref_no=allocate_case_ref_no(s, kohima),
            is_provisional=False,
        )
        s.add_all([provisional, elsewhere])
        s.commit()
        ref = provisional.ref_no
    h = ds.login(api, "root")
    r = api.post("/admin/data-load/collect", json={"kind": "cases", "refs": [ref]}, headers=h)
    assert r.status_code == 202, r.text
    rid = r.json()["request_id"]
    d = _detail(api, h, rid)
    assert [i["ref"] for i in d["items"]] == ["GAHC01|WA/77/2025"]
    assert [x["case"]["ref_no"] for x in d["results"]] == [ref]  # not the Kohima case with the same number
    # once fetched, the case its number resolved to is the request's (the CNR the dossier row found)
    with world.Session() as s:
        holder = make_case(s, cnr="GAHC010000772025", case_no="WA 77/2025")
        s.execute(
            sa.text(
                "UPDATE fetch_queue SET status = 'done', finished_at = now(), result = result || "
                "jsonb_build_object('cnr', CAST(:c AS text)) WHERE kind = 'dossier'"
            ),
            {"c": holder.cnr},
        )
        s.commit()
        holder_ref = holder.ref_no
    d = _detail(api, h, rid)
    assert d["finished"]
    assert {x["case"]["ref_no"] for x in d["results"]} == {ref, holder_ref}


def test_queue_origin_reads_the_parent_now(world):
    """`from_parent` reads the claimed row's priority and requests as they are when it spawns."""
    with world.Session() as s:
        queue.enqueue(s, FetchKind.DOSSIER, CNR_A, NOW_BULK, lane=FetchLane.REQUEST, request_ids=["r1"])
        row = queue.get_state(s, FetchKind.DOSSIER, CNR_A)
        origin = QueueOrigin(FetchLane.REQUEST, now_priority=NOW_BULK, parent_id=row.id)
        assert queue.from_parent(s, origin).now_priority == NOW_BULK
        assert queue.from_parent(s, origin).request_ids == ("r1",)
        s.execute(sa.text("UPDATE fetch_queue SET priority = 30"))
        out = queue.from_parent(s, origin)
        assert out.now_priority is None and out.order_pdf_priority(True) == REQUEST_ORDER_PDF
        assert queue.from_parent(s, QueueOrigin()).parent_id is None
        s.rollback()


def test_a_request_written_before_the_tags_keeps_the_earlier_rule(api, world):
    """A request record without `after.tagged` (written before the row 174 review): its own rows by the earlier rule
    (deviation 19) and no spawned items, so request-lane order PDFs of its case never count."""
    from aslms.domain.events import AuditLog

    with world.Session() as s:
        case = make_case(s, cnr=CNR_A)
        root = world.user(s, "root")
        asked = datetime.now(UTC) - timedelta(hours=1)
        row = AuditLog(
            action="napix.refetch_requested",
            entity_type="fetch_queue",
            after={"kind": "dossier", "ref": CNR_A, "priority": NOW_ONE},
            actor_user_id=root.id,
            actor_name="Root",
            created_at=asked,
        )
        s.add(row)
        s.flush()
        rid = str(row.id)
        queue.enqueue(s, FetchKind.DOSSIER, CNR_A, NOW_ONE, lane=FetchLane.REQUEST, requested_by=root.id)
        queue.enqueue(s, FetchKind.ORDER_PDF, f"{case.cnr}|1|2025-01-06", NOW_ONE, lane=FetchLane.REQUEST)
        s.commit()
    h = ds.login(api, "root")
    d = _detail(api, h, rid)
    assert [i["kind"] for i in d["items"]] == ["dossier"] and not d["finished"]
    with world.Session() as s:
        item = queue.claim(s, [FetchKind.DOSSIER])
        queue.complete(s, item)
        s.commit()
    d = _detail(api, h, rid)
    assert d["finished"] and d["total"] == 1  # the waiting order PDF is not its item


# ------------------------------------------------------------------------------------------------ B1: Retry All


@pytest.mark.parametrize("via", ["api", "cli"])
def test_retry_all_never_reopens_a_finished_bulk_request(api, world, monkeypatch, via):
    """Retry All (`POST /admin/napix/queue/retry-failed`, `aslms queue-retry-failed`) brings a failed item of a
    finished bulk request back as later work: without the request's id, so the request stays finished."""
    from contextlib import contextmanager

    import typer
    from typer.testing import CliRunner

    from aslms.cli import pipeline

    with world.Session() as s:
        make_case(s, cnr=CNR_A)
        make_case(s, cnr=CNR_B)
        s.commit()
    h = ds.login(api, "root")
    rid = api.post(
        "/admin/data-load/collect", json={"kind": "list", "lines": [CNR_A, CNR_B]}, headers=h
    ).json()["request_id"]
    with world.Session() as s:
        item = queue.claim(s, [FetchKind.DOSSIER], max_priority=NOW_BULK)
        queue.complete(s, item)
        item = queue.claim(s, [FetchKind.DOSSIER], max_priority=NOW_BULK)
        item.attempts = queue.MAX_ATTEMPTS
        queue.fail(s, item, "court busy")
        failed_ref = item.ref
        s.commit()
    assert _tags(world, FetchKind.DOSSIER)[failed_ref] == [rid]
    d = _detail(api, h, rid)
    assert d["finished"] and d["counts"]["failed"] == 1 and not d["using_everything"]
    if via == "api":
        r = api.post("/admin/napix/queue/retry-failed", json={"kind": "dossier"}, headers=h)
        assert r.status_code in (200, 202), r.text
    else:

        @contextmanager
        def scope():
            s = world.Session()
            try:
                yield s
                s.commit()
            finally:
                s.close()

        monkeypatch.setattr(pipeline, "session_scope", scope)
        app = typer.Typer()
        app.command(name="queue-retry-failed")(pipeline.queue_retry_failed)
        app.command(name="noop")(lambda: None)
        r = CliRunner().invoke(app, ["queue-retry-failed", "--kind", "dossier"])
        assert r.exit_code == 0, r.output
    with world.Session() as s:
        row = queue.get_state(s, FetchKind.DOSSIER, failed_ref)
        assert (row.status, row.priority, row.requested_by) == (FetchStatus.PENDING, 30, None)
    assert _tags(world, FetchKind.DOSSIER)[failed_ref] == []
    d = _detail(api, h, rid)
    assert d["finished"] and not d["using_everything"] and d["counts"]["waiting"] == 0
    with world.Session() as s:
        assert collect.active_bulk(s) is None
        assert collect.bulk_message(s, Settings(_env_file=None)) is None
    assert api.get("/admin/data-load/overview", headers=h).json()["bulk"] is None
    r = api.post("/admin/data-load/collect", json={"kind": "list", "lines": ["GAHC019999972025"]}, headers=h)
    assert r.status_code == 202, r.text


# ------------------------------------------------------------------------------------------------ A2: single Retry


def test_single_retry_brings_a_now_row_back_at_30_in_its_own_lane(api, world):
    """Retry on one failed row (Problems and Fixes): a row failed at a "now" priority comes back at 30, in its own
    lane and without its request's id; any other row keeps its priority and lane (the load's stays the load's)."""
    with world.Session() as s:
        queue.enqueue(s, FetchKind.DOSSIER, CNR_A, NOW_ONE, lane=FetchLane.REQUEST, request_ids=["r1"])
        queue.enqueue(s, FetchKind.DOSSIER, CNR_B, 44, lane=FetchLane.LOAD)
        for _ in range(2):
            item = queue.claim(s, [FetchKind.DOSSIER])
            item.attempts = queue.MAX_ATTEMPTS
            queue.fail(s, item, "court busy")
        ids = {r.ref: r.id for r in s.scalars(sa.select(FetchQueueItem)).all()}
        s.commit()
    h = ds.login(api, "root")
    for ref in (CNR_A, CNR_B):
        r = api.post(f"/admin/napix/queue/{ids[ref]}/retry", headers=h)
        assert r.status_code in (200, 202), r.text
    with world.Session() as s:
        now_row = queue.get_state(s, FetchKind.DOSSIER, CNR_A)
        load_row = queue.get_state(s, FetchKind.DOSSIER, CNR_B)
        assert (now_row.status, now_row.priority, now_row.lane) == (
            FetchStatus.PENDING,
            30,
            FetchLane.REQUEST,
        )
        assert not (now_row.result or {}).get("request_ids") and now_row.requested_by is None
        assert (load_row.status, load_row.priority, load_row.lane) == (
            FetchStatus.PENDING,
            44,
            FetchLane.LOAD,
        )
        assert not queue.has_now(s)


# ------------------------------------------------------------------------------------------------ A1, A3: spawned rows


def test_a_request_on_a_row_running_in_the_daily_lane_spawns_in_the_request_lane(api, world, napix, tmp_path):
    """The weekly sweep's dossier is running when a bulk request asks for the same case: the request takes it over
    (its id, its priority) and the order PDFs the run spawns are the request's, in the request lane, listed among its
    items and reached by Stop; never a "now" priority in the daily lane."""
    with world.Session() as s:
        make_case(s, cnr=CNR_A)
        queue.enqueue(s, FetchKind.DOSSIER, CNR_A, queue.PRIORITY["dossier_refetch"])
        claimed = Claimed.of(queue.claim(s, [FetchKind.DOSSIER]))
        s.commit()
    assert (claimed.lane, claimed.priority) == (FetchLane.DAILY, 50)
    h = ds.login(api, "root")
    r = api.post("/admin/data-load/collect", json={"kind": "list", "lines": [CNR_A]}, headers=h)
    assert r.status_code == 202 and r.json()["already_waiting"] == 1, r.text
    rid = r.json()["request_id"]
    _gw, client, hc = napix
    recorder = NapixRecorder()
    client.on_call = recorder.on_call

    async def finish():
        async with client:
            return await _runner(world, hc, tmp_path, recorder)._process(
                claimed.id,
                claimed.kind,
                claimed.ref,
                RunReport(),
                lane=claimed.lane,
                requested_by=claimed.requested_by,
                priority=claimed.priority,
            )

    assert asyncio.run(finish()) is None
    with world.Session() as s:
        pdfs = s.scalars(sa.select(FetchQueueItem).where(FetchQueueItem.kind == FetchKind.ORDER_PDF)).all()
        assert len(pdfs) == 3
        assert {(p.lane, p.priority) for p in pdfs} == {(FetchLane.REQUEST, NOW_BULK)}
        assert {tuple(p.result["request_ids"]) for p in pdfs} == {(rid,)}
    d = _detail(api, h, rid)
    assert not d["finished"] and d["using_everything"] and d["total"] == 4 and d["counts"]["waiting"] == 3
    r = api.post(f"/admin/data-load/requests/{rid}/stop", headers=h)
    assert r.status_code == 200 and r.json()["moved"] == 3, r.text
    with world.Session() as s:
        assert not queue.has_now(s)


def test_spawned_rows_of_a_provisional_reference_are_found_through_its_resolved_cnr(api, world):
    """The order PDFs are found through the request's own rows: a provisional dossier row's resolved CNR (its
    `result.cnr`) leads to that case's orders; a tagged PDF of a case the request never named is not looked at."""
    with world.Session() as s:
        principal = s.scalar(sa.select(Court).where(Court.est_code == "GAHC01"))
        provisional = Case(
            court_id=principal.id,
            case_no_text="WA/78/2025",
            ref_no=allocate_case_ref_no(s, principal),
            is_provisional=True,
        )
        s.add(provisional)
        s.flush()
        ref = provisional.ref_no
        s.commit()
    h = ds.login(api, "root")
    rid = api.post("/admin/data-load/collect", json={"kind": "cases", "refs": [ref]}, headers=h).json()[
        "request_id"
    ]
    with world.Session() as s:
        holder = make_case(s, cnr="GAHC010000782025")
        order = Order(
            case_id=holder.id,
            order_no="1",
            order_date=TODAY,
            kind=OrderKind.INTERIM,
            download_status=DownloadStatus.PENDING,
        )
        s.add(order)
        s.execute(
            sa.text(
                "UPDATE fetch_queue SET status = 'done', finished_at = now(), result = result || "
                "jsonb_build_object('cnr', CAST(:c AS text)) WHERE kind = 'dossier'"
            ),
            {"c": holder.cnr},
        )
        pdf_ref = f"{holder.cnr}|1|{TODAY.isoformat()}"
        queue.enqueue(s, FetchKind.ORDER_PDF, pdf_ref, NOW_ONE, lane=FetchLane.REQUEST, request_ids=[rid])
        # the same id on a PDF of a case the request never named (cannot happen in practice): not looked at
        queue.enqueue(
            s,
            FetchKind.ORDER_PDF,
            f"{CNR_B}|1|2025-01-06",
            NOW_ONE,
            lane=FetchLane.REQUEST,
            request_ids=[rid],
        )
        s.commit()
    d = _detail(api, h, rid)
    assert [(i["kind"], i["ref"], i["state"]) for i in d["items"]] == [
        ("dossier", "GAHC01|WA/78/2025", "done"),
        ("order_pdf", pdf_ref, "waiting"),
    ]
    assert not d["finished"]
