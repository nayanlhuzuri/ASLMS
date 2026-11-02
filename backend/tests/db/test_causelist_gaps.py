"""Cause-list days nobody asked for (design `causelist-day-gap-sweep`): the collection period, the days with no row,
the lane by age, the nightly sweep and its CLI, the daily cycle's catch-up at scheduler start and at 06:30 / 18:30,
the Overview's `not_asked` block and the schedule entry. The queue only: no NAPIX call on any path."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta

import pytest
import sqlalchemy as sa

from aslms.core.clock import today_ist
from aslms.core.config import Settings
from aslms.domain.events import AuditLog
from aslms.domain.ops import (
    DataLoadSettings,
    FetchKind,
    FetchLane,
    FetchQueueItem,
    FetchStatus,
    JobRun,
    JobStatus,
    LoadOrder,
    NapixCallLog,
)
from aslms.services import causelist_gaps as gaps
from aslms.services import data_load, schedules

TODAY = date(2026, 10, 28)
CFG = Settings(_env_file=None)


def cfg(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def D(month: int, day: int) -> date:
    return date(2026, month, day)


def _day(s, d: date, status: FetchStatus = FetchStatus.DONE, *, lane=FetchLane.LOAD, priority=46):
    row = FetchQueueItem(
        kind=FetchKind.CAUSELIST_DAY,
        ref=d.isoformat(),
        status=status,
        lane=lane,
        priority=priority,
        list_date=d,
    )
    s.add(row)
    s.flush()
    return row


def _days(s, first: date, last: date, **kw) -> None:
    d = first
    while d <= last:
        _day(s, d, **kw)
        d += timedelta(days=1)


def _rows(s) -> dict[date, FetchQueueItem]:
    items = s.scalars(
        sa.select(FetchQueueItem)
        .where(FetchQueueItem.kind == FetchKind.CAUSELIST_DAY)
        .execution_options(populate_existing=True)
    ).all()
    return {date.fromisoformat(r.ref): r for r in items}


def _runs(s, job: str) -> list[JobRun]:
    return s.scalars(sa.select(JobRun).where(JobRun.job == job).order_by(JobRun.started_at)).all()


def _count(s, model) -> int:
    return int(s.scalar(sa.select(sa.func.count()).select_from(model)))


def _settings_row(s, *, paused=False, order=LoadOrder.CASES_FIRST, first_from=None, first_to=None):
    s.add(
        DataLoadSettings(
            version=1,
            paused=paused,
            load_order=order,
            first_from=first_from,
            first_to=first_to,
            reason="test",
            is_current=True,
        )
    )
    s.flush()


# ------------------------------------------------------------------------------------------------ the period


def test_collection_start_is_earliest_load_or_daily_day_ignoring_request_lane(clean_db):
    with clean_db() as s:
        assert gaps.collection_start(s) is None
        _day(s, D(1, 5), lane=FetchLane.REQUEST)  # one person's old date does not stretch the period
        assert gaps.collection_start(s) is None
        _day(s, D(10, 6), lane=FetchLane.DAILY)
        assert gaps.collection_start(s) == D(10, 6)
        _day(s, D(9, 20), lane=FetchLane.LOAD)
        assert gaps.collection_start(s) == D(9, 20)
        s.add(FetchQueueItem(kind=FetchKind.DOSSIER, ref="0000-01-01", priority=40, lane=FetchLane.LOAD))
        s.flush()
        assert gaps.collection_start(s) == D(9, 20)  # only cause-list days


def test_no_rows_no_period_sweep_does_nothing_and_records_zero_missing(clean_db):
    with clean_db() as s:
        assert gaps.not_asked(s, today=TODAY) is None
        out = gaps.run_sweep(s, CFG, trigger="nightly", today=TODAY)
        assert out["missing"] == 0 and out["queued_daily"] == 0 and out["queued_load"] == 0
        assert out["from"] is None and out["ranges"] == []
        assert _rows(s) == {}
        (run,) = _runs(s, gaps.JOB_SWEEP)
        assert run.status == JobStatus.SUCCEEDED and run.counters["missing"] == 0
        assert run.counters["trigger"] == "nightly"


def test_missing_days_count_any_lane_and_any_status_as_asked(clean_db):
    with clean_db() as s:
        _day(s, D(10, 1), FetchStatus.DONE)
        _day(s, D(10, 2), FetchStatus.SKIPPED, lane=FetchLane.DAILY)
        _day(s, D(10, 3), FetchStatus.PENDING, lane=FetchLane.REQUEST)
        _day(s, D(10, 4), FetchStatus.RUNNING)
        _day(s, D(10, 5), FetchStatus.FAILED)
        assert gaps.missing_days(s, D(9, 30), D(10, 7)) == [D(9, 30), D(10, 6), D(10, 7)]
        assert gaps.missing_days(s, D(10, 7), D(10, 6)) == []
        assert gaps.ranges([D(10, 7), D(9, 30), D(10, 6), D(10, 1)]) == [
            (D(9, 30), D(10, 1)),
            (D(10, 6), D(10, 7)),
        ]


# ------------------------------------------------------------------------------------------------ the sweep


def test_reproduces_2_to_5_october(clean_db):
    with clean_db() as s:
        _days(s, D(9, 25), D(10, 1))  # the backdated load, set up to end on 1 Oct
        _days(s, D(10, 6), D(10, 27), lane=FetchLane.DAILY, priority=20)  # the daily cycle from 6 Oct
        out = gaps.run_sweep(s, CFG, trigger="nightly", today=TODAY)
        assert out["missing"] == 4 and out["queued_load"] == 4 and out["queued_daily"] == 0
        assert out["ranges"] == [{"from": "2026-10-02", "to": "2026-10-05", "days": 4}]
        rows = _rows(s)
        for d in (D(10, 2), D(10, 3), D(10, 4), D(10, 5)):
            r = rows[d]
            assert FetchLane(r.lane) == FetchLane.LOAD and r.priority == 46  # cases_first: lists second, 46
            assert (
                r.list_date == d and r.requested_by is None and FetchStatus(r.status) == FetchStatus.PENDING
            )
        assert len(rows) == 7 + 22 + 4


def test_recent_gaps_go_to_the_daily_lane_at_22_and_yesterday_at_20(clean_db):
    with clean_db() as s:
        _days(s, D(10, 1), D(10, 15))
        out = gaps.run_sweep(s, CFG, trigger="nightly", today=TODAY)
        assert out["missing"] == 12 and out["queued_daily"] == 7 and out["queued_load"] == 5
        rows = _rows(s)
        for n in range(16, 21):
            assert FetchLane(rows[D(10, n)].lane) == FetchLane.LOAD and rows[D(10, n)].priority == 46
        for n in range(21, 27):
            assert FetchLane(rows[D(10, n)].lane) == FetchLane.DAILY and rows[D(10, n)].priority == 22
        assert FetchLane(rows[D(10, 27)].lane) == FetchLane.DAILY and rows[D(10, 27)].priority == 20


def test_window_zero_sends_every_gap_to_the_load_lane(clean_db):
    with clean_db() as s:
        _days(s, D(10, 1), D(10, 15))
        out = gaps.run_sweep(s, cfg(causelist_catchup_days=0), trigger="nightly", today=TODAY)
        assert out["queued_daily"] == 0 and out["queued_load"] == 12
        assert {FetchLane(r.lane) for d, r in _rows(s).items() if d > D(10, 15)} == {FetchLane.LOAD}


def test_load_priority_follows_the_preset_and_the_period_brought_forward(clean_db):
    with clean_db() as s:
        _settings_row(s, order=LoadOrder.LISTS_FIRST, first_from=D(9, 3), first_to=D(9, 4))
        _day(s, D(9, 1))
        _day(s, D(9, 6))
        gaps.run_sweep(s, CFG, trigger="nightly", today=TODAY)
        rows = _rows(s)
        assert rows[D(9, 2)].priority == 44  # lists first, outside the period brought forward
        assert rows[D(9, 3)].priority == 41 and rows[D(9, 4)].priority == 41  # inside it
        assert rows[D(9, 5)].priority == 44


def test_sweep_never_queues_today_tomorrow_or_before_the_start(clean_db):
    with clean_db() as s:
        _day(s, D(10, 20), lane=FetchLane.DAILY)
        out = gaps.run_sweep(s, CFG, trigger="nightly", today=TODAY)
        rows = _rows(s)
        assert min(rows) == D(10, 20) and max(rows) == D(10, 27)
        assert out["from"] == "2026-10-20" and out["to"] == "2026-10-27" and out["missing"] == 7


def test_sweep_is_idempotent(clean_db):
    with clean_db() as s:
        _days(s, D(10, 1), D(10, 10))
        first = gaps.run_sweep(s, CFG, trigger="nightly", today=TODAY)
        second = gaps.run_sweep(s, CFG, trigger="nightly", today=TODAY)
        assert first["missing"] == 17 and first["queued_daily"] + first["queued_load"] == 17
        assert second["missing"] == 0 and second["queued_daily"] == 0 and second["queued_load"] == 0
        assert len(_runs(s, gaps.JOB_SWEEP)) == 2


def test_sweep_never_revives_failed_or_skipped_or_reprioritises(clean_db):
    with clean_db() as s:
        _day(s, D(10, 20), FetchStatus.FAILED, priority=46)
        _day(s, D(10, 22), FetchStatus.SKIPPED, priority=46)
        _day(s, D(10, 24), FetchStatus.PENDING, priority=46)  # within the window, but has a row: left at 46
        _day(s, D(10, 26), FetchStatus.DONE, lane=FetchLane.REQUEST, priority=30)
        before = {d: (r.status, r.priority, r.lane, r.attempts) for d, r in _rows(s).items()}
        out = gaps.run_sweep(s, CFG, trigger="nightly", today=TODAY)
        rows = _rows(s)
        assert {
            d: (r.status, r.priority, r.lane, r.attempts) for d, r in rows.items() if d in before
        } == before
        assert out["missing"] == 4  # 21, 23, 25, 27


def test_sweep_while_paused_queues_and_records_paused(clean_db):
    with clean_db() as s:
        _settings_row(s, paused=True)
        _days(s, D(9, 1), D(9, 10))
        out = gaps.run_sweep(s, CFG, trigger="nightly", today=TODAY)
        assert out["paused"] is True and out["queued_load"] > 0
        assert _runs(s, gaps.JOB_SWEEP)[-1].counters["paused"] is True


def test_sweep_job_run_counters_and_ranges_capped_at_20(clean_db):
    with clean_db() as s:
        # rows on every other day from 1 Sep: 25 one-day gaps, then the run of days to yesterday
        for n in range(26):
            _day(s, D(9, 1) + timedelta(days=2 * n))
        last = D(9, 1) + timedelta(days=50)
        _days(s, last + timedelta(days=1), TODAY - timedelta(days=1), lane=FetchLane.DAILY)
        out = gaps.run_sweep(s, CFG, trigger="nightly", today=TODAY)
        (run,) = _runs(s, gaps.JOB_SWEEP)
        assert run.counters == out
        assert out["missing"] == 25 and len(out["ranges"]) == 20 and out["more_ranges"] == 5
        assert out["ranges"][0] == {"from": "2026-09-02", "to": "2026-09-02", "days": 1}
        assert set(out) == {
            "trigger",
            "from",
            "to",
            "missing",
            "queued_daily",
            "queued_load",
            "ranges",
            "more_ranges",
            "paused",
        }


def test_sweep_failure_marks_run_failed_and_reraises(clean_db, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("queue down")

    monkeypatch.setattr(gaps, "queue_days", boom)
    with clean_db() as s:
        _day(s, D(10, 1))
        with pytest.raises(RuntimeError, match="queue down"):
            gaps.run_sweep(s, CFG, trigger="nightly", today=TODAY)
        (run,) = _runs(s, gaps.JOB_SWEEP)
        assert run.status == JobStatus.FAILED and "RuntimeError: queue down" in run.error
        assert run.finished_at is not None


def test_sweep_refuses_an_unknown_trigger(clean_db):
    with clean_db() as s:
        with pytest.raises(ValueError):
            gaps.run_sweep(s, CFG, trigger="hourly", today=TODAY)
        with pytest.raises(ValueError):
            gaps.catch_up(s, CFG, trigger="nightly", today=TODAY)


def test_nightly_sweep_writes_no_audit_row(clean_db):
    with clean_db() as s:
        _days(s, D(10, 1), D(10, 3))
        before = _count(s, AuditLog)
        out = gaps.run_sweep(s, CFG, trigger="nightly", today=TODAY)
        assert out["missing"] > 0 and _count(s, AuditLog) == before


def test_celery_task_runs_the_nightly_sweep(clean_db, monkeypatch):
    from aslms.jobs import celery_app

    @contextmanager
    def scope():
        s = clean_db()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    today = today_ist()
    with clean_db() as s:
        _days(s, today - timedelta(days=12), today - timedelta(days=11))
        s.commit()
    monkeypatch.setattr(celery_app, "session_scope", scope)
    out = celery_app.causelist_gap_sweep()
    assert out["trigger"] == "nightly" and out["missing"] == 10
    with clean_db() as s:
        assert _runs(s, gaps.JOB_SWEEP)[-1].counters["trigger"] == "nightly"
        assert _count(s, AuditLog) == 0


def _cli(world, monkeypatch):
    import typer

    from aslms.cli import data_load as cli
    from aslms.cli import pipeline

    @contextmanager
    def scope():
        s = world.Session()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    monkeypatch.setattr(cli, "session_scope", scope)
    monkeypatch.setattr(pipeline, "session_scope", scope)
    monkeypatch.setattr(cli, "get_settings", lambda: CFG)
    monkeypatch.setattr(gaps, "today_ist", lambda *a: TODAY)
    app = typer.Typer()
    app.add_typer(cli.data_load_app, name="data-load")
    return app


def _gap_world(world):
    with world.Session() as s:
        s.execute(sa.delete(FetchQueueItem))
        _days(s, D(9, 25), D(10, 1))
        _days(s, D(10, 6), D(10, 27), lane=FetchLane.DAILY, priority=20)
        s.commit()


def test_cli_apply_writes_gaps_queued_audit_row(world, monkeypatch):
    from typer.testing import CliRunner

    _gap_world(world)
    app = _cli(world, monkeypatch)
    r = CliRunner().invoke(app, ["data-load", "gaps", "--apply"])
    assert r.exit_code == 0, r.output
    assert "Collection period: 2026-09-25 to 2026-10-27" in r.output
    assert "Days not asked for: 4" in r.output
    assert "2026-10-02 to 2026-10-05 (4 days): load lane, priority 46" in r.output
    assert "Queued: 0 in the daily lane, 4 in the load lane" in r.output
    with world.Session() as s:
        (row,) = s.scalars(sa.select(AuditLog).where(AuditLog.action == "data_load.gaps_queued")).all()
        assert row.after["queued_load"] == 4 and row.after["trigger"] == "cli"
        assert row.entity_type == "fetch_queue"
        (run,) = _runs(s, gaps.JOB_SWEEP)
        assert run.counters["trigger"] == "cli" and run.status == JobStatus.SUCCEEDED
        assert sum(1 for d in _rows(s) if D(10, 2) <= d <= D(10, 5)) == 4
    r = CliRunner().invoke(app, ["data-load", "gaps"])
    assert r.exit_code == 0 and "Days not asked for: none" in r.output


def test_dry_run_writes_nothing(world, monkeypatch):
    from typer.testing import CliRunner

    _gap_world(world)
    with world.Session() as s:
        before = (_count(s, FetchQueueItem), _count(s, JobRun), _count(s, AuditLog))
        p = gaps.run_sweep(s, CFG, trigger="cli", today=TODAY, dry_run=True)
        assert p["missing"] == 4 and p["would_queue_load"] == 4
        assert p["ranges"] == [
            {
                "from": D(10, 2),
                "to": D(10, 5),
                "days": 4,
                "lane": FetchLane.LOAD,
                "priorities": [46],
            }
        ]
        s.commit()
    app = _cli(world, monkeypatch)
    r = CliRunner().invoke(app, ["data-load", "gaps"])
    assert r.exit_code == 0, r.output
    assert "Dry run: nothing written" in r.output and "Queued" not in r.output
    with world.Session() as s:
        assert (_count(s, FetchQueueItem), _count(s, JobRun), _count(s, AuditLog)) == before


# ------------------------------------------------------------------------------------------------ the catch-up


def test_catch_up_at_start_after_a_three_day_outage(clean_db):
    d0 = TODAY - timedelta(days=4)  # the last day the cycle ran for (rows to D); today is D+4
    with clean_db() as s:
        _days(s, d0 - timedelta(days=5), d0, lane=FetchLane.DAILY, priority=20)
        out = gaps.catch_up(s, CFG, trigger="start", today=TODAY)
        assert out["queued"] == [d0 + timedelta(days=n) for n in range(1, 6)]
        rows = _rows(s)
        for n in range(1, 6):
            r = rows[d0 + timedelta(days=n)]
            assert FetchLane(r.lane) == FetchLane.DAILY
            assert r.priority == (22 if n <= 2 else 20)
        (run,) = _runs(s, gaps.JOB_CATCHUP)
        assert run.status == JobStatus.SUCCEEDED and run.counters["trigger"] == "start"
        assert (
            run.counters["window_days"] == 7 and run.counters["to"] == (TODAY + timedelta(days=1)).isoformat()
        )
        assert run.counters["queued"] == [(d0 + timedelta(days=n)).isoformat() for n in range(1, 6)]


def test_catch_up_leaves_days_that_have_a_row(clean_db):
    with clean_db() as s:
        _days(s, TODAY - timedelta(days=10), TODAY - timedelta(days=3), lane=FetchLane.DAILY, priority=20)
        _day(s, TODAY, FetchStatus.DONE, lane=FetchLane.DAILY, priority=20)
        out = gaps.catch_up(s, CFG, trigger="start", today=TODAY)
        assert out["queued"] == [
            TODAY - timedelta(days=2),
            TODAY - timedelta(days=1),
            TODAY + timedelta(days=1),
        ]
        assert FetchStatus(_rows(s)[TODAY].status) == FetchStatus.DONE


def test_catch_up_bounded_by_collection_start(clean_db):
    with clean_db() as s:
        start = TODAY - timedelta(days=3)
        _day(s, start, lane=FetchLane.DAILY, priority=20)
        out = gaps.catch_up(s, CFG, trigger="start", today=TODAY)
        assert out["from"] == start
        assert min(_rows(s)) == start
        assert out["queued"] == [start + timedelta(days=n) for n in range(1, 5)]


def test_catch_up_on_an_empty_install_queues_only_the_three_days(clean_db):
    with clean_db() as s:
        assert gaps.catch_up(s, CFG, trigger="morning", today=TODAY)["queued"] == []
        out = gaps.catch_up(s, CFG, trigger="start", today=TODAY)
        assert out["queued"] == [TODAY - timedelta(days=1), TODAY, TODAY + timedelta(days=1)]
        assert {(FetchLane(r.lane), r.priority) for r in _rows(s).values()} == {(FetchLane.DAILY, 20)}


def test_morning_and_evening_runs_fill_the_window_and_return_caught_up(clean_db):
    d0 = TODAY - timedelta(days=4)
    with clean_db() as s:
        _days(s, d0 - timedelta(days=5), d0, lane=FetchLane.DAILY, priority=20)
        out = schedules.enqueue_morning_lists(s, TODAY, cfg(causelist_recheck_morning=False))
        assert out == {"days": 3, "rechecks": 0, "caught_up": 2}
        rows = _rows(s)
        assert rows[d0 + timedelta(days=1)].priority == 22 and rows[d0 + timedelta(days=2)].priority == 22
        (run,) = _runs(s, gaps.JOB_CATCHUP)
        assert run.counters["trigger"] == "morning"
        assert run.counters["to"] == (TODAY - timedelta(days=2)).isoformat()
    with clean_db() as s:
        _days(s, d0 - timedelta(days=5), d0, lane=FetchLane.DAILY, priority=20)
        out = schedules.enqueue_evening_lists(s, TODAY, CFG)
        assert out == {"days": 3, "rechecks": 2, "caught_up": 2}
        assert _runs(s, gaps.JOB_CATCHUP)[0].counters["trigger"] == "evening"


def test_catch_up_error_never_loses_the_three_days(clean_db, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("catch-up down")

    monkeypatch.setattr(gaps, "catch_up", boom)
    with clean_db() as s:
        out = schedules.enqueue_morning_lists(s, TODAY, cfg(causelist_recheck_morning=False))
        assert out == {"days": 3, "rechecks": 0, "caught_up": 0}
        assert len(_rows(s)) == 3


def test_catch_up_with_nothing_missing_writes_no_run(clean_db):
    with clean_db() as s:
        _days(s, TODAY - timedelta(days=20), TODAY + timedelta(days=1), lane=FetchLane.DAILY, priority=20)
        assert gaps.catch_up(s, CFG, trigger="start", today=TODAY)["queued"] == []
        assert schedules.enqueue_evening_lists(s, TODAY, CFG)["caught_up"] == 0
        assert _runs(s, gaps.JOB_CATCHUP) == []


def test_celery_catchup_task_at_start(clean_db, monkeypatch):
    from aslms.jobs import celery_app

    @contextmanager
    def scope():
        s = clean_db()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    monkeypatch.setattr(celery_app, "session_scope", scope)
    out = celery_app.lists_catchup()
    assert out["trigger"] == "start" and len(out["queued"]) == 3
    assert all(isinstance(d, str) for d in out["queued"])
    with clean_db() as s:
        assert len(_runs(s, gaps.JOB_CATCHUP)) == 1


# ------------------------------------------------------------------------------------------------ overview, schedule


def test_overview_not_asked_matches_the_sweep(clean_db):
    now = datetime(2026, 10, 28, 6, 0, tzinfo=UTC)  # 11:30 IST on 28 Oct 2026
    with clean_db() as s:
        assert data_load.overview(s, CFG, now)["not_asked"] is None
        for n in range(23):  # 22 one-day gaps from 2 Sep
            _day(s, D(9, 1) + timedelta(days=2 * n))
        _days(s, D(10, 20), D(10, 27), lane=FetchLane.DAILY)
        block = data_load.overview(s, CFG, now)["not_asked"]
        p = gaps.plan(s, CFG, today=TODAY)
        assert block["count"] == p["missing"] == 22 + (D(10, 19) - D(9, 1) - timedelta(days=44)).days
        assert block["from"] == D(9, 1) and block["to"] == D(10, 27)
        assert len(block["ranges"]) == 20 and block["more_ranges"] == 3
        assert block["ranges"][0] == {"from": D(9, 2), "to": D(9, 2), "days": 1}
        assert [r["from"] for r in block["ranges"]] == sorted(r["from"] for r in block["ranges"])
        out = gaps.run_sweep(s, CFG, trigger="nightly", today=TODAY)
        assert out["missing"] == block["count"]
        assert data_load.overview(s, CFG, now)["not_asked"]["count"] == 0


def test_schedule_view_has_the_gap_sweep_with_last_run_and_facts(clean_db):
    now = datetime.now(UTC)
    with clean_db() as s:
        entries = {e["key"]: e for e in schedules.schedule_view(s, CFG, now)["entries"]}
        gap = entries["day-gaps"]
        assert gap["when"] == "04:15" and gap["last_run_at"] is None and gap["facts"] == {}
        assert gap["what"] == "Ask the court for past days' cause lists never asked for"
        s.add(
            JobRun(
                job=gaps.JOB_SWEEP,
                started_at=now - timedelta(hours=3),
                status=JobStatus.SUCCEEDED,
                counters={"missing": 5, "queued_daily": 2, "queued_load": 3},
            )
        )
        s.flush()
        gap = {e["key"]: e for e in schedules.schedule_view(s, CFG, now)["entries"]}["day-gaps"]
        assert gap["result"] == "succeeded" and gap["facts"] == {"queued": 5, "missing": 5}
        assert gap["last_run_at"] == now - timedelta(hours=3)


def test_no_napix_call_log_row(clean_db, monkeypatch):
    with clean_db() as s:
        _days(s, D(9, 1), D(9, 3))
        _days(s, TODAY - timedelta(days=12), TODAY - timedelta(days=9), lane=FetchLane.DAILY)
        gaps.run_sweep(s, CFG, trigger="nightly", today=TODAY, dry_run=True)
        gaps.not_asked(s, today=TODAY)
        gaps.catch_up(s, CFG, trigger="start", today=TODAY)
        schedules.enqueue_morning_lists(s, TODAY, CFG)
        schedules.enqueue_evening_lists(s, TODAY, CFG)
        gaps.run_sweep(s, CFG, trigger="nightly", today=TODAY)
        data_load.overview(s, CFG, datetime(2026, 10, 28, 6, 0, tzinfo=UTC))
        schedules.schedule_view(s, CFG)
        assert _count(s, NapixCallLog) == 0
