"""The "now" priorities in the runner and the worker (design `data-collection-redesign`, decisions 23-24; round 3):
a "now" row is claimed outside the reserve bands and the discovery share and stops only at the court's own limit; one
case (3) runs before a bulk request (5); what a "now" row spawns inherits its priority and person; the calls log the
person; the sleeping worker wakes within 2 s; the fault pause still applies."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

import httpx
import sqlalchemy as sa

from aslms.cli.pipeline import NOW_POLL_SECONDS, has_now_check, nap
from aslms.core.config import Settings
from aslms.domain.ops import FetchKind, FetchLane, FetchQueueItem, FetchStatus, NapixCallLog
from aslms.services import queue
from aslms.services.load_policy import NOW_BULK, NOW_ONE
from aslms.services.napix_store import NapixRecorder
from aslms.services.runner import QueueRunner, RunReport
from aslms.services.storage import LocalStore
from tests.db.conftest import router

DAY = date(2025, 1, 6)
CNR = "GAHC010129772026"


def _settings(tmp_path, **kw) -> Settings:
    return Settings(
        _env_file=None, storage_dir=str(tmp_path / "store"), causelist_dir=str(tmp_path / "lists"), **kw
    )


def _runner(Session, hc, tmp_path, recorder=None, **kw) -> QueueRunner:
    settings = _settings(tmp_path, **kw)
    return QueueRunner(
        Session,
        hc,
        settings=settings,
        store=LocalStore(settings.storage_dir),
        causelist_dir=tmp_path / "lists",
        recorder=recorder or NapixRecorder(),
    )


def _log_call(s, remaining: int, lane: str | None = None) -> None:
    s.add(
        NapixCallLog(
            api="hc-cnr-api/CNR",
            params_sha256="x" * 64,
            ok=True,
            rate_limit_remaining=remaining,
            lane=lane,
            called_at=datetime.now(UTC),
        )
    )


def _states(Session) -> dict[str, FetchStatus]:
    with Session() as s:
        return {r.ref: r.status for r in s.scalars(sa.select(FetchQueueItem)).all()}


def _reset(Session, remaining: int | None) -> None:
    with Session() as s:
        s.execute(sa.text("DELETE FROM fetch_queue"))
        s.execute(sa.text("DELETE FROM napix_call_log"))
        if remaining is not None:
            _log_call(s, remaining)
        s.commit()


def _days(s, *specs: tuple[str, int, FetchLane]) -> None:
    """Cause-list days; with no NAPIX client and no website files each ends `skipped` when claimed."""
    for ref, priority, lane in specs:
        queue.enqueue(s, FetchKind.CAUSELIST_DAY, ref, priority, lane=lane, list_date=date.fromisoformat(ref))


def test_now_rows_are_claimed_below_the_live_reserve_and_ignore_the_discovery_share(clean_db, tmp_path):
    Session = clean_db
    _reset(Session, 80)  # below the live reserve (100): the bands claim nothing
    with Session() as s:
        _days(
            s,
            ("2025-01-04", NOW_ONE, FetchLane.REQUEST),
            ("2025-01-05", NOW_BULK, FetchLane.REQUEST),
            ("2025-01-06", 20, FetchLane.DAILY),
            ("2025-01-07", 30, FetchLane.REQUEST),
        )
        s.commit()
    rep = asyncio.run(_runner(Session, None, tmp_path).run(max_items=10))
    assert _states(Session) == {
        "2025-01-04": FetchStatus.SKIPPED,
        "2025-01-05": FetchStatus.SKIPPED,
        "2025-01-06": FetchStatus.PENDING,
        "2025-01-07": FetchStatus.PENDING,  # a request at 30 keeps the bands
    }
    assert rep.processed == 2 and rep.stopped_reason.startswith("rate budget")
    # the discovery share spent (0) and the reserves high: a "now" row still runs
    _reset(Session, 140)
    with Session() as s:
        _days(s, ("2025-01-08", NOW_ONE, FetchLane.REQUEST), ("2025-01-09", 46, FetchLane.LOAD))
        s.commit()
    rep = asyncio.run(_runner(Session, None, tmp_path, napix_discovery_share=0).run(max_items=10))
    assert _states(Session) == {"2025-01-08": FetchStatus.SKIPPED, "2025-01-09": FetchStatus.PENDING}


def test_now_rows_stop_only_at_the_courts_limit(clean_db, tmp_path):
    Session = clean_db
    _reset(Session, 0)
    with Session() as s:
        _days(s, ("2025-01-04", NOW_ONE, FetchLane.REQUEST))
        s.commit()
    rep = asyncio.run(_runner(Session, None, tmp_path).run(max_items=5))
    assert rep.processed == 0 and _states(Session) == {"2025-01-04": FetchStatus.PENDING}
    assert rep.resume_at is not None and rep.remaining == 0 and not rep.now_may_wake()
    _reset(Session, 1)
    with Session() as s:
        _days(s, ("2025-01-04", NOW_ONE, FetchLane.REQUEST))
        s.commit()
    rep = asyncio.run(_runner(Session, None, tmp_path).run(max_items=5))
    assert rep.processed == 1 and _states(Session) == {"2025-01-04": FetchStatus.SKIPPED}


def test_one_case_now_row_runs_before_a_bulk_now_row(clean_db):
    with clean_db() as s:
        queue.enqueue(s, FetchKind.MASTERS, "all", 10)
        _days(
            s,
            ("2025-01-06", 20, FetchLane.DAILY),
            ("2025-01-05", NOW_BULK, FetchLane.REQUEST),
            ("2025-01-04", NOW_ONE, FetchLane.REQUEST),
        )
        assert queue.has_now(s)
        order = [queue.claim(s) for _ in range(4)]
        assert [c.ref for c in order] == ["2025-01-04", "2025-01-05", "all", "2025-01-06"]
        assert not queue.has_now(s)
        s.rollback()


def _run_kind(world, napix, tmp_path, kinds, max_items=1, **kw):
    gw, client, hc = napix
    recorder = NapixRecorder()
    client.on_call = recorder.on_call

    async def go():
        async with client:
            return await _runner(world.Session, hc, tmp_path, recorder, **kw).run(
                max_items=max_items, kinds=kinds
            )

    return asyncio.run(go())


def test_now_dossier_spawns_every_missing_order_pdf_at_the_same_priority(world, napix, tmp_path):
    with world.Session() as s:
        person = world.user(s, "root").id
        queue.enqueue(s, FetchKind.DOSSIER, CNR, NOW_ONE, lane=FetchLane.REQUEST, requested_by=person)
        s.commit()
    rep = _run_kind(world, napix, tmp_path, [FetchKind.DOSSIER])
    assert rep.done == 1, rep.items
    with world.Session() as s:
        pdfs = s.scalars(sa.select(FetchQueueItem).where(FetchQueueItem.kind == FetchKind.ORDER_PDF)).all()
        assert len(pdfs) == 3
        assert {(p.lane, p.priority, p.requested_by) for p in pdfs} == {(FetchLane.REQUEST, NOW_ONE, person)}
        # a pending daily-lane PDF of the same case is lifted to the "now" priority and the request lane
        s.execute(sa.text("UPDATE fetch_queue SET priority = 60, lane = 'daily', requested_by = NULL"))
        s.execute(
            sa.text("UPDATE fetch_queue SET status = 'pending', priority = :p WHERE kind = 'dossier'"),
            {"p": NOW_BULK},
        )
        s.execute(
            sa.text("UPDATE fetch_queue SET lane = 'request', requested_by = :u WHERE kind = 'dossier'"),
            {"u": person},
        )
        s.commit()
    rep = _run_kind(world, napix, tmp_path, [FetchKind.DOSSIER])
    with world.Session() as s:
        pdfs = s.scalars(sa.select(FetchQueueItem).where(FetchQueueItem.kind == FetchKind.ORDER_PDF)).all()
        assert {(p.lane, p.priority, p.requested_by) for p in pdfs} == {(FetchLane.REQUEST, NOW_BULK, person)}


def test_now_day_spawns_new_dossiers_at_the_same_priority(world, napix, tmp_path):
    with world.Session() as s:
        person = world.user(s, "root").id
        queue.enqueue(
            s, FetchKind.CAUSELIST_DAY, DAY.isoformat(), NOW_BULK, lane=FetchLane.REQUEST, requested_by=person
        )
        s.commit()
    rep = _run_kind(world, napix, tmp_path, [FetchKind.CAUSELIST_DAY])
    assert rep.done == 1, rep.items
    with world.Session() as s:
        dossiers = s.scalars(sa.select(FetchQueueItem).where(FetchQueueItem.kind == FetchKind.DOSSIER)).all()
        assert len(dossiers) == 9
        assert {(d.lane, d.priority, d.requested_by) for d in dossiers} == {
            (FetchLane.REQUEST, NOW_BULK, person)
        }


def test_now_rows_log_calls_under_the_person(world, napix, tmp_path):
    with world.Session() as s:
        person = world.user(s, "root").id
        queue.enqueue(s, FetchKind.DOSSIER, CNR, NOW_ONE, lane=FetchLane.REQUEST, requested_by=person)
        s.commit()
    rep = _run_kind(world, napix, tmp_path, None, max_items=4)
    assert rep.processed == 4, rep.items  # the dossier, then its three order PDFs at once
    with world.Session() as s:
        rows = s.execute(sa.select(NapixCallLog.api, NapixCallLog.user_id, NapixCallLog.lane)).all()
    queued = [(api, uid, lane) for api, uid, lane in rows if api != "overview/overview"]
    assert queued and {(uid, lane) for _, uid, lane in queued} == {(person, FetchLane.REQUEST)}
    assert {api for api, _, _ in queued} >= {"hc-cnr-api/CNR"}


def test_worker_wait_wakes_within_two_seconds_for_a_now_row(clean_db):
    Session = clean_db
    with Session() as s:
        s.execute(sa.text("DELETE FROM fetch_queue"))
        s.commit()
    slept: list[float] = []
    clock = {"t": 0.0}

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        clock["t"] += seconds
        if clock["t"] >= 7 and not _states(Session):  # a person asks 7 s into the sleep
            with Session() as s:
                queue.enqueue(s, FetchKind.DOSSIER, CNR, NOW_ONE, lane=FetchLane.REQUEST)
                s.commit()

    total = nap(60.0, has_now_check(Session), sleep=sleep)
    assert all(step <= NOW_POLL_SECONDS for step in slept)
    assert 7 <= total <= 7 + NOW_POLL_SECONDS
    # a row waiting at an ordinary priority does not wake it
    with Session() as s:
        s.execute(sa.text("UPDATE fetch_queue SET priority = 30"))
        s.commit()
    assert nap(10.0, has_now_check(Session), sleep=lambda _: None) == 10.0
    # without a wake the sleep is one piece
    calls: list[float] = []
    assert nap(30.0, None, sleep=calls.append) == 30.0 and calls == [30.0]


def test_now_may_wake_only_when_the_court_has_calls_left():
    assert RunReport().now_may_wake()  # an idle pass, the remaining count unknown
    assert RunReport(remaining=80).now_may_wake()  # the bands stopped the pass; the court still answers
    assert not RunReport(remaining=0).now_may_wake()  # the court's own limit
    assert not RunReport(remaining=500, fault_pause=True).now_may_wake()
    assert not RunReport(probe_failed=True).now_may_wake()


def test_fault_pause_still_applies_to_now_rows(clean_db, napix, tmp_path):
    gw, client, hc = napix
    Session = clean_db
    with Session() as s:
        for i in range(5):
            queue.enqueue(s, FetchKind.DOSSIER, f"GAHC0100000001{i:02d}", NOW_ONE, lane=FetchLane.REQUEST)
        s.commit()
    base = router(gw)

    def handle(path, q, request):
        if path == "hc-cnr-api/CNR":
            return httpx.Response(200, text="")
        return base(path, q, request)

    gw.responses = [handle] * 10_000
    recorder = NapixRecorder()
    client.on_call = recorder.on_call

    async def go():
        async with client:
            return await _runner(Session, hc, tmp_path, recorder, napix_fault_streak=3).run()

    rep = asyncio.run(go())
    assert rep.fault_pause and rep.processed == 3 and rep.failed == 3
    assert not rep.now_may_wake()
    with Session() as s:
        waiting = s.scalar(
            sa.select(sa.func.count()).where(
                FetchQueueItem.status == FetchStatus.PENDING, FetchQueueItem.attempts == 0
            )
        )
        assert waiting == 2
