"""Design `safety-fixes` (database): the retry ladder and its mirror in `source_failures`, a person's re-fetch
brought forward, the runner's fault pause and its handling of an empty HTTP 200, `search_rows` never claimed by the
runner, the widened weekly sweep, `aslms queue-retry-failed` and migration 0019."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import sqlalchemy as sa
from alembic import command
from typer.testing import CliRunner

from aslms.core.config import Settings
from aslms.domain.cases import Case, CaseStatus
from aslms.domain.events import AuditLog
from aslms.domain.ops import FetchKind, FetchLane, FetchQueueItem, FetchStatus, SourceFailure
from aslms.services import queue, source_failures
from aslms.services.napix_store import NapixRecorder
from aslms.services.runner import QueueRunner
from aslms.services.storage import LocalStore
from aslms.services.tracking import enqueue_weekly_dossier_sweep
from tests.db.conftest import alembic_config, head_revision, router, wipe, wipe_if_migrated
from tests.db.world import make_case

LADDER_MINUTES = [10, 60, 360, 1440, 4320]


def _now() -> datetime:
    return datetime.now(UTC)


def _due_now(s, item: FetchQueueItem) -> None:
    item.not_before = _now() - timedelta(seconds=1)
    s.flush()


# ------------------------------------------------------------------------------------------------ the queue


def test_queue_retry_ladder_10m_1h_6h_24h_72h_then_failed(clean_db):
    with clean_db() as s:
        queue.enqueue(s, FetchKind.DOSSIER, "GAHC010000000011", 40)
        for n, minutes in enumerate(LADDER_MINUTES, start=1):
            item = queue.claim(s)
            assert item is not None and item.attempts == n
            before = _now()
            queue.fail(s, item, "NapixEmptyResponse: NAPIX empty response", family="NapixEmptyResponse")
            assert item.status == FetchStatus.PENDING
            wait = (item.not_before - before).total_seconds()
            assert minutes * 60 - 5 <= wait <= minutes * 60 + 5, (n, wait)
            assert queue.claim(s) is None  # waits on the ladder
            _due_now(s, item)
        item = queue.claim(s)
        assert item.attempts == queue.MAX_ATTEMPTS == 6
        queue.fail(s, item, "NapixEmptyResponse: NAPIX empty response", family="NapixEmptyResponse")
        assert item.status == FetchStatus.FAILED
        s.rollback()


def test_failed_row_mirrored_to_source_failures_and_resolved_on_done(clean_db):
    ref = "GAHC010000000012"
    with clean_db() as s:
        queue.enqueue(s, FetchKind.DOSSIER, ref, 40)
        for _ in range(queue.MAX_ATTEMPTS):
            item = queue.claim(s)
            assert s.scalar(sa.select(sa.func.count()).select_from(SourceFailure)) == 0  # not yet final
            queue.fail(s, item, "NapixUnavailable: NAPIX HTTP 503", family="NapixUnavailable")
            if item.status == FetchStatus.PENDING:
                _due_now(s, item)
        assert item.status == FetchStatus.FAILED
        sf = s.scalar(sa.select(SourceFailure).where(SourceFailure.kind == "fetch_dossier"))
        assert sf.ref == ref and sf.error == "NapixUnavailable: NAPIX HTTP 503"
        assert sf.error_family == "NapixUnavailable" and sf.attempts == 1 and sf.resolved_at is None
        # revived, then done: the failure is resolved
        assert queue.enqueue(s, FetchKind.DOSSIER, ref, 40)
        item = queue.claim(s)
        assert item.attempts == 1
        queue.complete(s, item, {"ok": True})
        s.refresh(sf)
        assert sf.resolved_at is not None
        # a second final failure reopens the same row and bumps it
        source_failures.record(s, "fetch_dossier", ref, "again", "NapixEmptyResponse")
        s.refresh(sf)
        assert sf.resolved_at is None and sf.attempts == 2 and sf.error_family == "NapixEmptyResponse"
        assert source_failures.resolve(s, "fetch_dossier", ref) == 1
        assert source_failures.resolve(s, "fetch_dossier", ref) == 0
        s.rollback()


def test_request_enqueue_brings_pending_row_forward_daily_does_not(world):
    with world.Session() as s:
        person = world.user(s, "edu_admin").id
        for ref in ("GAHC010000000013", "GAHC010000000014"):
            queue.enqueue(s, FetchKind.DOSSIER, ref, 50)
            item = queue.claim(s)
            queue.fail(s, item, "NapixEmptyResponse: x", family="NapixEmptyResponse")
            item.not_before = _now() + timedelta(hours=24)  # a late step of the ladder
            item.attempts = 4
            s.flush()
        # the daily cycle asking again keeps the wait
        queue.enqueue(s, FetchKind.DOSSIER, "GAHC010000000013", 40, lane=FetchLane.DAILY)
        daily = queue.get_state(s, FetchKind.DOSSIER, "GAHC010000000013")
        assert daily.not_before > _now() + timedelta(hours=23) and daily.attempts == 4
        # a person asking again runs now; attempts and the ladder position are kept
        queue.enqueue(
            s, FetchKind.DOSSIER, "GAHC010000000014", 30, lane=FetchLane.REQUEST, requested_by=person
        )
        asked = queue.get_state(s, FetchKind.DOSSIER, "GAHC010000000014")
        assert asked.not_before is None and asked.attempts == 4 and asked.lane == FetchLane.REQUEST
        assert asked.requested_by == person
        assert queue.claim(s).ref == "GAHC010000000014"
        s.rollback()


# ------------------------------------------------------------------------------------------------ the runner


def _settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        storage_dir=str(tmp_path / "store"),
        causelist_dir=str(tmp_path / "lists"),
        napix_rate_reserve=0,
        napix_live_reserve=0,
        napix_search_floor=0,
    )


def _scripted(gw, script: list[str]):
    """The sample router, except that Search by CNR answers from `script` ("empty" = HTTP 200 with no body)."""
    base = router(gw)

    def handle(path, q, request):
        if path == "hc-cnr-api/CNR" and script:
            if script.pop(0) == "empty":
                return httpx.Response(200, text="")
        return base(path, q, request)

    gw.responses = [handle] * 10_000


def _run(Session, napix, tmp_path, max_items=None, kinds=None):
    gw, client, hc = napix
    settings = _settings(tmp_path)
    recorder = NapixRecorder()
    client.on_call = recorder.on_call

    async def go():
        async with client:
            runner = QueueRunner(
                Session,
                hc,
                settings=settings,
                store=LocalStore(settings.storage_dir),
                causelist_dir=tmp_path / "lists",
                recorder=recorder,
                reserve=0,
            )
            return await runner.run(max_items=max_items, kinds=kinds)

    return asyncio.run(go())


def test_runner_pauses_after_fault_streak(clean_db, napix, tmp_path):
    gw = napix[0]
    Session = clean_db
    with Session() as s:
        for i in range(7):
            queue.enqueue(s, FetchKind.DOSSIER, f"GAHC0100000001{i:02d}", 40 + i)
        s.commit()
    _scripted(gw, ["empty"] * 7)
    started = _now()
    rep = _run(Session, napix, tmp_path)
    assert rep.fault_pause and rep.processed == 5 and rep.failed == 5
    assert rep.stopped_reason == "gateway fault: 5 failures in a row; pausing 300 s"
    assert started + timedelta(seconds=290) <= rep.resume_at <= _now() + timedelta(seconds=310)
    with Session() as s:
        rows = s.scalars(sa.select(FetchQueueItem).order_by(FetchQueueItem.priority)).all()
        assert [r.attempts for r in rows] == [1, 1, 1, 1, 1, 0, 0]
        assert all(r.status == FetchStatus.PENDING for r in rows)
        assert all(r.not_before is not None for r in rows[:5]) and rows[5].not_before is None
        assert {r.last_error.split(":")[0] for r in rows[:5]} == {"NapixEmptyResponse"}
        families = s.execute(
            sa.text("select error_family, count(*) from napix_call_log where not ok group by 1")
        ).all()
        assert dict(families) == {"NapixEmptyResponse": 5}  # one attempt per item, no in-call retry
    # one success in between resets the count
    with Session() as s:
        for i in range(10):
            queue.enqueue(s, FetchKind.DOSSIER, f"GAHC0100000002{i:02d}", 20 + i)
        s.commit()
    _scripted(gw, ["empty"] * 4 + ["ok"] + ["empty"] * 5)
    rep = _run(Session, napix, tmp_path)
    assert rep.fault_pause and rep.processed == 10 and rep.done == 1 and rep.failed == 9


def test_empty_200_dossier_retried_by_ladder_then_succeeds(clean_db, napix, tmp_path):
    gw = napix[0]
    Session = clean_db
    cnr = "GAHC010000000301"
    with Session() as s:
        queue.enqueue(s, FetchKind.DOSSIER, cnr, 40)
        s.commit()
    _scripted(gw, ["empty"])
    rep = _run(Session, napix, tmp_path, max_items=1)
    assert rep.failed == 1 and not rep.fault_pause
    with Session() as s:
        row = queue.get_state(s, FetchKind.DOSSIER, cnr)
        assert row.status == FetchStatus.PENDING and row.attempts == 1
        assert timedelta(minutes=9) < row.not_before - _now() <= timedelta(minutes=10)
        assert s.scalar(sa.select(Case).where(Case.cnr == cnr)) is None  # nothing left behind
        row.not_before = _now() - timedelta(seconds=1)
        s.commit()
    rep = _run(Session, napix, tmp_path, max_items=1, kinds=[FetchKind.DOSSIER])
    assert rep.done == 1, rep.items
    with Session() as s:
        row = queue.get_state(s, FetchKind.DOSSIER, cnr)
        assert row.status == FetchStatus.DONE and row.attempts == 2
        case = s.scalar(sa.select(Case).where(Case.cnr == cnr))
        assert case is not None and case.last_full_refresh_at is not None
        assert s.scalar(sa.select(sa.func.count()).select_from(SourceFailure)) == 0


def test_runner_never_claims_search_rows(clean_db, tmp_path):
    Session = clean_db
    rid = "0192f000-0000-7000-8000-000000000001"
    with Session() as s:
        queue.enqueue(s, FetchKind.SEARCH_ROWS, rid, 30, lane=FetchLane.REQUEST)
        s.commit()
        assert not queue.has_runnable(s)
        assert queue.has_runnable(s, [FetchKind.SEARCH_ROWS])
        assert queue.claim(s) is None
        s.rollback()
    runner = QueueRunner(Session, None, settings=_settings(tmp_path), reserve=0)
    rep = asyncio.run(runner.run())
    assert rep.processed == 0 and rep.stopped_reason == "queue empty"
    with Session() as s:
        row = queue.get_state(s, FetchKind.SEARCH_ROWS, rid)
        assert row.status == FetchStatus.PENDING and row.attempts == 0
        with pytest.raises(RuntimeError, match="not run by the queue runner"):
            asyncio.run(runner.dispatch(s, FetchKind.SEARCH_ROWS, rid))


# ------------------------------------------------------------------------------------------------ the weekly sweep


def test_weekly_sweep_includes_never_fetched_disposed_and_cnr_less_cases(world):
    with world.Session() as s:
        never = make_case(s, cnr="GAHC010000000401", status=CaseStatus.DISPOSED)
        fetched = make_case(s, cnr="GAHC010000000402", status=CaseStatus.DISPOSED)
        fetched.last_full_refresh_at = _now()
        live = make_case(s, cnr="GAHC010000000403", status=CaseStatus.PENDING)
        live.last_full_refresh_at = _now()
        provisional = make_case(s, case_no="WP(C)/77/2025", status=CaseStatus.UNKNOWN)
        provisional.cnr, provisional.is_provisional = None, True
        s.flush()
        # the never-fetched case's dossier row failed for good earlier
        queue.enqueue(s, FetchKind.DOSSIER, never.cnr, 50)
        failed = queue.claim(s)
        failed.attempts = queue.MAX_ATTEMPTS
        queue.fail(s, failed, "NapixEmptyResponse: x", family="NapixEmptyResponse")
        assert failed.status == FetchStatus.FAILED
        s.commit()
    with world.Session() as s:
        n = enqueue_weekly_dossier_sweep(s)
        s.commit()
        rows = {
            r.ref: r
            for r in s.scalars(sa.select(FetchQueueItem).where(FetchQueueItem.kind == FetchKind.DOSSIER))
        }
    assert n == 3
    assert set(rows) == {"GAHC010000000401", "GAHC010000000403", "GAHC01|WP(C)/77/2025"}
    revived = rows["GAHC010000000401"]
    assert revived.status == FetchStatus.PENDING and revived.attempts == 0
    assert all(r.priority == 50 and r.lane == FetchLane.DAILY for r in rows.values())


# ------------------------------------------------------------------------------------------------ the CLI


def _scope(world):
    @contextmanager
    def scope():
        s = world.Session()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    return scope


def test_queue_retry_failed_cli_revives_and_audits(world, monkeypatch):
    import typer

    from aslms.cli import pipeline

    with world.Session() as s:
        for ref in ("GAHC010000000501", "GAHC010000000502"):
            queue.enqueue(s, FetchKind.DOSSIER, ref, 40)
            item = queue.claim(s)
            item.attempts = queue.MAX_ATTEMPTS
            queue.fail(s, item, "NapixEmptyResponse: x", family="NapixEmptyResponse")
        s.commit()
    monkeypatch.setattr(pipeline, "session_scope", _scope(world))
    app = typer.Typer()
    app.command(name="queue-retry-failed")(pipeline.queue_retry_failed)
    app.command(name="noop")(lambda: None)
    runner = CliRunner()
    r = runner.invoke(app, ["queue-retry-failed", "--kind", "dossier"])
    assert r.exit_code == 0, r.output
    assert "retried 2 failed dossier row(s)" in r.output
    r = runner.invoke(app, ["queue-retry-failed", "--kind", "nonsense"])
    assert r.exit_code != 0
    with world.Session() as s:
        rows = s.scalars(sa.select(FetchQueueItem)).all()
        assert all(x.status == FetchStatus.PENDING and x.attempts == 0 for x in rows)
        audit = s.scalars(sa.select(AuditLog).where(AuditLog.action == "napix.queue_retry_failed")).all()
        assert len(audit) == 1 and audit[0].after == {"kind": "dossier", "lane": None, "retried": 2}
        assert audit[0].actor_user_id == world.users["root"].id


# ------------------------------------------------------------------------------------------------ migration 0019


def test_migration_0019_adds_kind_and_downgrade_refuses_while_pending(db_url, engine):
    cfg = alembic_config(db_url)
    wipe_if_migrated(db_url)
    command.downgrade(cfg, "0018")
    try:
        command.upgrade(cfg, "head")
        with engine.connect() as conn:
            kinds = conn.execute(sa.text("select enum_range(NULL::fetch_kind)::text")).scalar()
        assert "search_rows" in kinds
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "insert into fetch_queue (kind, ref, priority, lane) "
                    "values ('search_rows', '0192f000-0000-7000-8000-000000000009', 30, 'request')"
                )
            )
        with pytest.raises(RuntimeError, match="0019"):
            command.downgrade(cfg, "0018")
        with engine.connect() as conn:
            assert (
                conn.execute(sa.text("select version_num from alembic_version")).scalar() == head_revision()
            )
        with engine.begin() as conn:
            conn.execute(sa.text("update fetch_queue set status = 'done'"))
        command.downgrade(cfg, "0018")
        with engine.connect() as conn:
            assert conn.execute(sa.text("select version_num from alembic_version")).scalar() == "0018"
            # PostgreSQL cannot drop an enum value: it stays, unused
            assert (
                "search_rows" in conn.execute(sa.text("select enum_range(NULL::fetch_kind)::text")).scalar()
            )
    finally:
        command.upgrade(cfg, "head")
        with engine.begin() as conn:
            wipe(conn)
