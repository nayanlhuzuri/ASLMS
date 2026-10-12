"""Queue lanes, the pause and the budget bands (design `data-load-console`, decisions 1, 2, 4, 5 and 7) against the
test database: the lane precedence on enqueue, spawned rows inheriting the lane and the list date, the pause read by
the claim query, the runner's bands seeded from the call log, the lane on each logged call, live order PDFs at 40."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

import sqlalchemy as sa

from aslms.core.config import Settings
from aslms.domain.cases import Case, CaseStatus, FirstSeenSource
from aslms.domain.courts import Court
from aslms.domain.ops import (
    DataLoadSettings,
    FetchKind,
    FetchLane,
    FetchQueueItem,
    FetchStatus,
    LoadOrder,
    NapixCallLog,
)
from aslms.services import court_search, queue
from aslms.services.audit import Actor
from aslms.services.cases import apply_dossier, get_or_create_case
from aslms.services.load_policy import QueueOrigin
from aslms.services.napix_store import NapixRecorder
from aslms.services.orders import enqueue_order_pdfs
from aslms.services.runner import QueueRunner
from aslms.services.storage import LocalStore
from tests.db.conftest import sample

DAY = date(2025, 1, 6)


def _row(s, kind: FetchKind, ref: str) -> FetchQueueItem:
    return s.scalar(
        sa.select(FetchQueueItem)
        .where(FetchQueueItem.kind == kind, FetchQueueItem.ref == ref)
        .execution_options(populate_existing=True)
    )


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


def _log_call(s, remaining: int, lane: str | None = None, at: datetime | None = None) -> None:
    s.add(
        NapixCallLog(
            api="hc-cnr-api/CNR",
            params_sha256="x" * 64,
            ok=True,
            rate_limit_remaining=remaining,
            lane=lane,
            called_at=at or datetime.now(UTC),
        )
    )


def test_lane_precedence_on_enqueue(clean_db):
    with clean_db() as s:
        queue.enqueue(s, FetchKind.DOSSIER, "GAHC010000000001", 44, lane=FetchLane.LOAD, list_date=DAY)
        queue.enqueue(s, FetchKind.DOSSIER, "GAHC010000000001", 40)  # today's list needs it too
        row = _row(s, FetchKind.DOSSIER, "GAHC010000000001")
        assert (row.lane, row.priority, row.list_date) == (FetchLane.DAILY, 40, DAY)
        queue.enqueue(s, FetchKind.DOSSIER, "GAHC010000000002", 40, list_date=date(2026, 10, 10))
        queue.enqueue(s, FetchKind.DOSSIER, "GAHC010000000002", 44, lane=FetchLane.LOAD, list_date=DAY)
        row = _row(s, FetchKind.DOSSIER, "GAHC010000000002")
        assert (row.lane, row.priority, row.list_date) == (FetchLane.DAILY, 40, date(2026, 10, 10))
        queue.enqueue(s, FetchKind.DOSSIER, "GAHC010000000002", 30, lane=FetchLane.REQUEST)
        row = _row(s, FetchKind.DOSSIER, "GAHC010000000002")
        assert (row.lane, row.priority) == (FetchLane.REQUEST, 30)
        # a done row asked again without requeue keeps its lane
        row.status = FetchStatus.DONE
        s.flush()
        queue.enqueue(s, FetchKind.DOSSIER, "GAHC010000000002", 44, lane=FetchLane.LOAD)
        assert _row(s, FetchKind.DOSSIER, "GAHC010000000002").lane == FetchLane.REQUEST
        s.rollback()


def test_spawned_rows_inherit_lane_and_list_date(clean_db, napix, tmp_path):
    gw, client, hc = napix
    Session = clean_db
    recorder = NapixRecorder()
    client.on_call = recorder.on_call
    with Session() as s:
        queue.enqueue(s, FetchKind.CAUSELIST_DAY, DAY.isoformat(), 46, lane=FetchLane.LOAD, list_date=DAY)
        s.commit()

    async def run(kinds, max_items=None):
        async with client:
            return await _runner(Session, hc, tmp_path, recorder).run(max_items=max_items, kinds=kinds)

    rep = asyncio.run(run([FetchKind.CAUSELIST_DAY]))
    assert rep.done == 1, rep.items
    with Session() as s:
        dossiers = s.scalars(sa.select(FetchQueueItem).where(FetchQueueItem.kind == FetchKind.DOSSIER)).all()
        assert len(dossiers) == 9
        assert {(d.lane, d.list_date, d.priority) for d in dossiers} == {(FetchLane.LOAD, DAY, 44)}
    rep = asyncio.run(run([FetchKind.DOSSIER], max_items=1))
    assert rep.done == 1, rep.items
    with Session() as s:
        pdfs = s.scalars(sa.select(FetchQueueItem).where(FetchQueueItem.kind == FetchKind.ORDER_PDF)).all()
        assert len(pdfs) == 3
        assert {(p.lane, p.list_date, p.priority) for p in pdfs} == {(FetchLane.LOAD, DAY, 48)}


def test_pause_skips_only_load(clean_db):
    with clean_db() as s:
        queue.enqueue(s, FetchKind.DOSSIER, "GAHC010000000001", 41, lane=FetchLane.LOAD, list_date=DAY)
        queue.enqueue(s, FetchKind.DOSSIER, "GAHC010000000002", 45)
        queue.enqueue(s, FetchKind.DOSSIER, "GAHC010000000003", 47, lane=FetchLane.REQUEST)
        s.add(
            DataLoadSettings(
                version=1, paused=True, load_order=LoadOrder.CASES_FIRST, reason="test", is_current=True
            )
        )
        s.flush()
        claimed = [queue.claim(s), queue.claim(s), queue.claim(s)]
        assert [c.ref if c else None for c in claimed] == ["GAHC010000000002", "GAHC010000000003", None]
        current = s.scalar(sa.select(DataLoadSettings).where(DataLoadSettings.is_current.is_(True)))
        current.is_current, current.valid_to = False, datetime.now(UTC)
        s.flush()
        s.add(
            DataLoadSettings(
                version=2, paused=False, load_order=LoadOrder.CASES_FIRST, reason="resumed", is_current=True
            )
        )
        s.flush()
        item = queue.claim(s)
        assert item is not None and item.ref == "GAHC010000000001" and item.lane == FetchLane.LOAD
        s.rollback()


def _two_days(s) -> None:
    """A load day and a daily day; with no NAPIX client and no website files both end `skipped` when claimed."""
    queue.enqueue(
        s, FetchKind.CAUSELIST_DAY, "2025-01-04", 46, lane=FetchLane.LOAD, list_date=date(2025, 1, 4)
    )
    queue.enqueue(s, FetchKind.CAUSELIST_DAY, "2025-01-05", 20, list_date=date(2025, 1, 5))


def _band_run(Session, tmp_path, remaining: int | None):
    with Session() as s:
        s.execute(sa.text("DELETE FROM fetch_queue"))
        s.execute(sa.text("DELETE FROM napix_call_log"))
        _two_days(s)
        if remaining is not None:
            _log_call(s, remaining)
        s.commit()
    rep = asyncio.run(_runner(Session, None, tmp_path).run(max_items=5))
    with Session() as s:
        states = {
            r.ref: r.status
            for r in s.scalars(sa.select(FetchQueueItem)).all()
            if r.kind == FetchKind.CAUSELIST_DAY
        }
    return rep, states


def test_budget_bands(clean_db, tmp_path):
    rep, states = _band_run(clean_db, tmp_path, 140)
    assert states == {"2025-01-05": FetchStatus.SKIPPED, "2025-01-04": FetchStatus.PENDING}
    assert rep.stopped_reason.startswith("load waits")
    rep, states = _band_run(clean_db, tmp_path, 90)
    assert states == {"2025-01-05": FetchStatus.PENDING, "2025-01-04": FetchStatus.PENDING}
    assert rep.processed == 0 and rep.stopped_reason.startswith("rate budget")
    rep, states = _band_run(clean_db, tmp_path, 200)
    assert states == {"2025-01-05": FetchStatus.SKIPPED, "2025-01-04": FetchStatus.SKIPPED}


def test_pass_seeds_remaining_from_call_log(clean_db, tmp_path):
    Session = clean_db
    with Session() as s:
        queue.enqueue(
            s, FetchKind.CAUSELIST_DAY, "2025-01-04", 46, lane=FetchLane.LOAD, list_date=date(2025, 1, 4)
        )
        _log_call(s, 120)
        s.commit()
    runner = _runner(Session, None, tmp_path)
    assert runner.recorder.last_remaining is None  # a fresh pass
    rep = asyncio.run(runner.run(max_items=5))
    assert rep.processed == 0 and runner.recorder.last_remaining == 120
    with Session() as s:
        assert _row(s, FetchKind.CAUSELIST_DAY, "2025-01-04").status == FetchStatus.PENDING
        # a reading outside the window lookback (6 h) does not count
        s.execute(sa.text("DELETE FROM napix_call_log"))
        _log_call(s, 10, at=datetime(2025, 1, 1, tzinfo=UTC))
        s.commit()
    rep = asyncio.run(_runner(Session, None, tmp_path).run(max_items=5))
    assert rep.processed == 1


def test_call_log_lane_recorded(clean_db, napix, tmp_path):
    gw, client, hc = napix
    Session = clean_db
    recorder = NapixRecorder()
    client.on_call = recorder.on_call
    with Session() as s:
        queue.enqueue(s, FetchKind.DOSSIER, "GAHC010020342016", 44, lane=FetchLane.LOAD, list_date=DAY)
        s.commit()

    async def go():
        async with client:
            await _runner(Session, hc, tmp_path, recorder).run(max_items=1)
            with Session() as s:
                await court_search.search_court(
                    s,
                    Actor.system("test"),
                    None,
                    {"kind": "cnr", "cnr": "GAHC010129772026"},
                    hc=hc,
                    recorder=recorder,
                    settings=_settings(tmp_path),
                )
                s.commit()

    asyncio.run(go())
    with Session() as s:
        rows = s.execute(sa.select(NapixCallLog.api, NapixCallLog.lane)).all()
    assert {lane for api, lane in rows if api == "hc-cnr-api/CNR"} == {FetchLane.LOAD, None}
    assert sum(1 for _, lane in rows if lane == FetchLane.LOAD) == 1
    assert sum(1 for api, lane in rows if lane is None and api != "overview/overview") == 1
    # no reading yet: the pass first probed the window once (design napix-window, decision 4), lane NULL
    assert [lane for api, lane in rows if api == "overview/overview"] == [None]


def test_live_order_pdfs_at_40(clean_db):
    with clean_db() as s:
        court = s.scalar(sa.select(Court).where(Court.est_code == "GAHC01"))
        case, _ = get_or_create_case(
            s, court, cnr="GAHC010129772026", case_no=None, source=FirstSeenSource.SEARCH
        )
        apply_dossier(s, case, {**sample("cnr_pending.json"), "cino": "GAHC010129772026"})
        assert case.status == CaseStatus.PENDING
        assert enqueue_order_pdfs(s, case) == 3
        rows = s.scalars(sa.select(FetchQueueItem).where(FetchQueueItem.kind == FetchKind.ORDER_PDF)).all()
        assert {(r.lane, r.priority) for r in rows} == {(FetchLane.DAILY, 40)}
        s.execute(sa.text("DELETE FROM fetch_queue"))
        case.status = CaseStatus.DISPOSED
        s.flush()
        enqueue_order_pdfs(s, case)
        rows = s.scalars(sa.select(FetchQueueItem).where(FetchQueueItem.kind == FetchKind.ORDER_PDF)).all()
        assert {(r.lane, r.priority) for r in rows} == {(FetchLane.DAILY, 80)}
        s.execute(sa.text("DELETE FROM fetch_queue"))
        enqueue_order_pdfs(s, case, QueueOrigin(FetchLane.REQUEST))
        rows = s.scalars(sa.select(FetchQueueItem).where(FetchQueueItem.kind == FetchKind.ORDER_PDF)).all()
        assert {(r.lane, r.priority) for r in rows} == {(FetchLane.REQUEST, 40)}
        s.rollback()
    with clean_db() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(Case)) == 0
