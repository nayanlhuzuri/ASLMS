"""Cause-list days nobody asked for (design `causelist-day-gap-sweep`): the nightly sweep, the daily cycle's catch-up
after an outage, and the days named on the Overview and in `aslms data-load status`.

- The collection period (decision 1) starts at the earliest `causelist_day` row of the `load` or `daily` lane (a
  person's `request`-lane fetch of an old date does not stretch it) and runs to yesterday (IST); with no such row
  there is no period.
- A day "not asked for" (decision 2) has no `causelist_day` row at all, whatever its lane and status: a done,
  skipped, pending, running or failed row is never re-queued, revived or re-prioritised here.
- Lane by age (decision 3): a missing day within the last `CAUSELIST_CATCHUP_DAYS` days goes to the `daily` lane at 22
  (`queue.PRIORITY["list_catchup"]`; yesterday, today and tomorrow at 20 as the daily cycle), an older one to the
  `load` lane at `load_priority` (41-46); `list_date` is the day, no person.
- `run_sweep` (decisions 4 and 7): the 04:15 IST beat job `causelist-gap-sweep` and `aslms data-load gaps --apply`,
  one `job_runs` row `causelist-gap-sweep`; the CLI's run also writes `data_load.gaps_queued`; a dry run writes
  nothing.
- `catch_up` (decision 5): at scheduler start (today − window to tomorrow) and inside the 06:30 / 18:30 list runs
  (today − window to today − 2); a `job_runs` row `lists-catchup` only when it queued a day.

Writes only `fetch_queue`, `job_runs` and (a person's `--apply`) `audit_log`; no NAPIX call, and `NAPIX_ENABLED` is not
read: the worker fetches the rows through the integration layer as any `causelist_day` row."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aslms.core.clock import today_ist
from aslms.domain.ops import FetchKind, FetchLane, FetchQueueItem, JobRun, JobStatus
from aslms.services import queue
from aslms.services.audit import Actor, write_audit
from aslms.services.load_policy import LoadSettings, current_settings, load_priority

JOB_SWEEP = "causelist-gap-sweep"
JOB_CATCHUP = "lists-catchup"
MAX_RANGES = 20
TRIGGERS_SWEEP = ("nightly", "cli")
TRIGGERS_CATCHUP = ("start", "morning", "evening")


def collection_start(session: Session) -> date | None:
    """Decision 1: the smallest `ref` of the `causelist_day` rows of the `load` and `daily` lanes (ISO dates, so text
    order is date order), or None."""
    ref = session.scalar(
        select(func.min(FetchQueueItem.ref)).where(
            FetchQueueItem.kind == FetchKind.CAUSELIST_DAY,
            FetchQueueItem.lane.in_([FetchLane.LOAD, FetchLane.DAILY]),
        )
    )
    if ref is None:
        return None
    try:
        return date.fromisoformat(ref)
    except ValueError:
        return None


def missing_days(session: Session, start: date, end: date) -> list[date]:
    """Decision 2: the days from `start` to `end` with no `causelist_day` row in any lane or status, oldest first."""
    if start > end:
        return []
    refs = set(
        session.scalars(
            select(FetchQueueItem.ref).where(
                FetchQueueItem.kind == FetchKind.CAUSELIST_DAY,
                FetchQueueItem.ref >= start.isoformat(),
                FetchQueueItem.ref <= end.isoformat(),
            )
        ).all()
    )
    out = []
    d = start
    while d <= end:
        if d.isoformat() not in refs:
            out.append(d)
        d += timedelta(days=1)
    return out


def ranges(days: list[date]) -> list[tuple[date, date]]:
    """Consecutive days folded into (first, last) pairs, oldest first."""
    out: list[tuple[date, date]] = []
    for d in sorted(days):
        if out and d == out[-1][1] + timedelta(days=1):
            out[-1] = (out[-1][0], d)
        else:
            out.append((d, d))
    return out


def _range_dicts(days: list[date], cap: int = MAX_RANGES) -> tuple[list[dict[str, Any]], int]:
    folded = ranges(days)
    shown = [{"from": a, "to": b, "days": (b - a).days + 1} for a, b in folded[:cap]]
    return shown, max(0, len(folded) - cap)


def _iso(value: Any) -> Any:
    """JSON-ready (for `job_runs.counters` and `audit_log.after`): dates as ISO text, in nested lists and dicts."""
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _iso(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_iso(v) for v in value]
    return value


def lane_for(day: date, *, today: date, settings: LoadSettings, catchup_days: int) -> tuple[FetchLane, int]:
    """Decision 3: the lane and priority of a missing day."""
    if day >= today - timedelta(days=catchup_days):
        pr = (
            queue.PRIORITY["list_today"]
            if day >= today - timedelta(days=1)
            else queue.PRIORITY["list_catchup"]
        )
        return FetchLane.DAILY, pr
    return FetchLane.LOAD, load_priority(settings, FetchKind.CAUSELIST_DAY, day)


def _queue(
    session: Session, days: list[date], *, today: date, settings: LoadSettings, catchup_days: int
) -> list[tuple[date, FetchLane]]:
    queued = []
    for d in days:
        lane, pr = lane_for(d, today=today, settings=settings, catchup_days=catchup_days)
        if queue.enqueue(
            session, FetchKind.CAUSELIST_DAY, d.isoformat(), pr, requeue=False, lane=lane, list_date=d
        ):
            queued.append((d, lane))
    return queued


def queue_days(
    session: Session, days: list[date], *, today: date, settings: LoadSettings, catchup_days: int
) -> dict[str, int]:
    """Decision 3: one `causelist_day` row per day, `requeue=False`. `{queued_daily, queued_load}`."""
    queued = _queue(session, days, today=today, settings=settings, catchup_days=catchup_days)
    return {
        "queued_daily": sum(1 for _, lane in queued if lane == FetchLane.DAILY),
        "queued_load": sum(1 for _, lane in queued if lane == FetchLane.LOAD),
    }


def _period(session: Session, today: date) -> tuple[date, date] | None:
    start = collection_start(session)
    yesterday = today - timedelta(days=1)
    if start is None or start > yesterday:
        return None
    return start, yesterday


def not_asked(session: Session, *, today: date | None = None) -> dict[str, Any] | None:
    """Decision 6: `{from, to, count, ranges: [{from, to, days}] (oldest first, at most 20), more_ranges}` over the
    collection period to yesterday, exactly what the next sweep would queue; None without a period. Reads only."""
    today = today or today_ist()
    period = _period(session, today)
    if period is None:
        return None
    days = missing_days(session, *period)
    shown, more = _range_dicts(days)
    return {"from": period[0], "to": period[1], "count": len(days), "ranges": shown, "more_ranges": more}


def plan(session: Session, cfg, *, today: date | None = None) -> dict[str, Any]:
    """The dry run's view: the period, the missing days folded into ranges split by lane, each with the lane and
    priority it would take. Reads only."""
    today = today or today_ist()
    settings = current_settings(session)
    period = _period(session, today)
    days = missing_days(session, *period) if period else []
    by_range: list[dict[str, Any]] = []
    for d in days:
        lane, pr = lane_for(d, today=today, settings=settings, catchup_days=cfg.causelist_catchup_days)
        last = by_range[-1] if by_range else None
        if last and last["lane"] == lane and last["to"] + timedelta(days=1) == d:
            last["to"], last["days"] = d, last["days"] + 1
            last["priorities"] = sorted({*last["priorities"], pr})
        else:
            by_range.append({"from": d, "to": d, "days": 1, "lane": lane, "priorities": [pr]})
    return {
        "from": period[0] if period else None,
        "to": period[1] if period else today - timedelta(days=1),
        "missing": len(days),
        "would_queue_daily": sum(r["days"] for r in by_range if r["lane"] == FetchLane.DAILY),
        "would_queue_load": sum(r["days"] for r in by_range if r["lane"] == FetchLane.LOAD),
        "ranges": by_range,
        "paused": settings.paused,
    }


def run_sweep(
    session: Session,
    cfg,
    *,
    trigger: str,
    today: date | None = None,
    actor: Actor | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Decisions 4 and 7: queue every missing day of the collection period to yesterday by decision 3 and record one
    `job_runs` row `causelist-gap-sweep` (`failed` with the error, then re-raised); with `actor`, also one audit row
    `data_load.gaps_queued`. A dry run returns `plan` and writes nothing."""
    if trigger not in TRIGGERS_SWEEP:
        raise ValueError(f"unknown trigger {trigger!r}")
    today = today or today_ist()
    if dry_run:
        return plan(session, cfg, today=today)
    run = JobRun(job=JOB_SWEEP, run_date=today)
    session.add(run)
    session.flush()
    try:
        settings = current_settings(session)
        period = _period(session, today)
        days = missing_days(session, *period) if period else []
        counts = queue_days(
            session, days, today=today, settings=settings, catchup_days=cfg.causelist_catchup_days
        )
        shown, more = _range_dicts(days)
        counters = _iso(
            {
                "trigger": trigger,
                "from": period[0] if period else None,
                "to": period[1] if period else today - timedelta(days=1),
                "missing": len(days),
                **counts,
                "ranges": shown,
                "more_ranges": more,
                "paused": settings.paused,
            }
        )
    except Exception as exc:  # noqa: BLE001 — recorded on the run, then re-raised for the worker log
        run.status, run.error = JobStatus.FAILED, f"{exc.__class__.__name__}: {exc}"[:2000]
        run.finished_at = datetime.now(UTC)
        session.flush()
        raise
    run.counters = counters
    run.status = JobStatus.SUCCEEDED
    run.finished_at = datetime.now(UTC)
    session.flush()
    if actor is not None:
        write_audit(session, actor, "data_load.gaps_queued", "fetch_queue", None, after=counters)
    return counters


def catch_up(session: Session, cfg, *, trigger: str, today: date | None = None) -> dict[str, Any]:
    """Decision 5: the missing days of the window (today − `CAUSELIST_CATCHUP_DAYS` to tomorrow at `start`, to
    today − 2 at `morning` / `evening`), bounded below by the collection start; with no start, yesterday to tomorrow
    at `start` only. Queued by decision 3; one `job_runs` row `lists-catchup` when a day was queued. Returns
    `{trigger, window_days, from, to, queued: [dates]}`."""
    if trigger not in TRIGGERS_CATCHUP:
        raise ValueError(f"unknown trigger {trigger!r}")
    today = today or today_ist()
    window = cfg.causelist_catchup_days
    start = collection_start(session)
    if trigger == "start":
        hi = today + timedelta(days=1)
        lo = today - timedelta(days=1) if start is None else max(today - timedelta(days=window), start)
    else:
        hi = today - timedelta(days=2)
        lo = max(today - timedelta(days=window), start) if start is not None else None
    days = missing_days(session, lo, hi) if lo is not None else []
    queued = _queue(session, days, today=today, settings=current_settings(session), catchup_days=window)
    out = {
        "trigger": trigger,
        "window_days": window,
        "from": lo,
        "to": hi,
        "queued": [d for d, _ in queued],
    }
    if queued:
        session.add(
            JobRun(
                job=JOB_CATCHUP,
                run_date=today,
                status=JobStatus.SUCCEEDED,
                finished_at=datetime.now(UTC),
                counters=_iso(out),
            )
        )
        session.flush()
    return out
