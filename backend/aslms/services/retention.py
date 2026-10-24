"""Retention of the NAPIX logs (design `court-data-freshness`, decisions 18-21; owner decision 12).

- `napix_call_log` is kept for `NAPIX_CALL_LOG_KEEP_DAYS` (730) IST days. The daily 03:45 IST job `napix-log-purge`
  deletes the rows called before the IST midnight of that many days ago, in batches of `NAPIX_CALL_LOG_PURGE_BATCH`,
  each committed on its own, for at most `NAPIX_CALL_LOG_PURGE_MAX_SECONDS`; rows left over make the run `partial` and
  the next night goes on. This is the one deletion DB_STANDARD §6 allows (a log, not a record); `aslms_app` holds
  DELETE on the table since 0001. One `job_runs` row per run and, when rows were deleted, one `audit_log` row
  `napix.call_log_purged` (system actor `napix-log-purge`). A plain DELETE: no session feature (PgBouncer).
- `napix_responses` is never purged (decision 21): `retention_report` only reads its size, to revisit the rule with
  real numbers.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from aslms.core.clock import ist_midnight, today_ist
from aslms.domain.ops import JobRun, JobStatus
from aslms.services.audit import Actor, write_audit

JOB = "napix-log-purge"
ACTION = "napix.call_log_purged"

_DELETE = text(
    """
    DELETE FROM napix_call_log WHERE id IN (
        SELECT id FROM napix_call_log WHERE called_at < :cutoff ORDER BY called_at LIMIT :batch)
    RETURNING called_at
    """
)


@dataclass
class PurgeReport:
    keep_days: int
    cutoff: datetime
    deleted: int = 0
    batches: int = 0
    more: bool = False
    oldest_kept_at: datetime | None = None
    seconds: float = 0.0
    first_called_at: datetime | None = None
    last_called_at: datetime | None = None
    dry_run: bool = False
    status: str = "succeeded"
    job_run_id: Any = None

    def counters(self) -> dict[str, Any]:
        return {
            "keep_days": self.keep_days,
            "cutoff": self.cutoff.isoformat(),
            "deleted": self.deleted,
            "batches": self.batches,
            "more": self.more,
            "oldest_kept_at": self.oldest_kept_at.isoformat() if self.oldest_kept_at else None,
            "seconds": round(self.seconds, 3),
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.counters(),
            "dry_run": self.dry_run,
            "status": self.status,
            "cutoff_date": self.cutoff_date().isoformat(),
            "first_called_at": self.first_called_at.isoformat() if self.first_called_at else None,
            "last_called_at": self.last_called_at.isoformat() if self.last_called_at else None,
        }

    def cutoff_date(self) -> date:
        return today_ist(self.cutoff)


def cutoff_for(keep_days: int, now: datetime | None = None) -> datetime:
    """IST midnight of `today_ist − keep_days`, as a UTC-aware datetime (decision 19)."""
    return ist_midnight(today_ist(now) - timedelta(days=keep_days))


def _oldest(session: Session) -> datetime | None:
    return session.scalar(text("SELECT min(called_at) FROM napix_call_log"))


def _count_before(session: Session, cutoff: datetime) -> int:
    return int(
        session.scalar(text("SELECT count(*) FROM napix_call_log WHERE called_at < :c"), {"c": cutoff}) or 0
    )


def purge_call_log(
    session_factory: sessionmaker[Session],
    settings,
    *,
    now: datetime | None = None,
    dry_run: bool = False,
    batch: int | None = None,
    max_seconds: float | None = None,
    monotonic=time.monotonic,
) -> PurgeReport:
    """Decision 19. The dry run counts the rows older than the cut-off and writes nothing (no `job_runs`, no audit)."""
    keep_days = settings.napix_call_log_keep_days
    batch = batch or settings.napix_call_log_purge_batch
    limit = settings.napix_call_log_purge_max_seconds if max_seconds is None else max_seconds
    cutoff = cutoff_for(keep_days, now)
    report = PurgeReport(keep_days=keep_days, cutoff=cutoff, dry_run=dry_run)
    started = monotonic()
    if dry_run:
        with session_factory() as s:
            report.deleted = _count_before(s, cutoff)
            report.oldest_kept_at = _oldest(s)
            s.rollback()
        report.seconds = monotonic() - started
        return report
    with session_factory() as s:
        run = JobRun(job=JOB, run_date=today_ist(now))
        s.add(run)
        s.commit()
        report.job_run_id = run.id
    error: str | None = None
    try:
        while True:
            with session_factory() as s:
                stamps = list(s.scalars(_DELETE, {"cutoff": cutoff, "batch": batch}).all())
                s.commit()
            if stamps:
                report.batches += 1
                report.deleted += len(stamps)
                lo, hi = min(stamps), max(stamps)
                report.first_called_at = (
                    lo if report.first_called_at is None else min(report.first_called_at, lo)
                )
                report.last_called_at = (
                    hi if report.last_called_at is None else max(report.last_called_at, hi)
                )
            if len(stamps) < batch:
                report.more = False
                break
            if monotonic() - started >= limit:
                with session_factory() as s:
                    report.more = _count_before(s, cutoff) > 0
                break
    except Exception as exc:  # noqa: BLE001 — recorded on the run, then re-raised for the worker log
        error = f"{exc.__class__.__name__}: {exc}"[:2000]
        raise
    finally:
        report.seconds = monotonic() - started
        with session_factory() as s:
            report.oldest_kept_at = _oldest(s)
            report.status = "failed" if error else ("partial" if report.more else "succeeded")
            run = s.get(JobRun, report.job_run_id)
            if run is not None:
                run.counters = report.counters()
                run.status = JobStatus(report.status)
                run.error = error
                run.finished_at = datetime.now(UTC)
            if report.deleted > 0:
                write_audit(
                    s,
                    Actor.system(JOB),
                    ACTION,
                    "napix_call_log",
                    None,
                    after={
                        "cutoff": cutoff.isoformat(),
                        "keep_days": keep_days,
                        "deleted": report.deleted,
                        "first_called_at": report.first_called_at,
                        "last_called_at": report.last_called_at,
                    },
                )
            s.commit()
    return report


def retention_report(session: Session) -> dict[str, Any]:
    """Read-only (decision 21): row counts per API and year and the on-disk size of `napix_call_log` and
    `napix_responses`, and the oldest call kept."""
    sizes = session.execute(
        text(
            "SELECT pg_total_relation_size('napix_call_log'), pg_total_relation_size('napix_responses'), "
            "(SELECT min(called_at) FROM napix_call_log)"
        )
    ).one()
    calls = session.execute(
        text(
            "SELECT api, extract(year FROM called_at AT TIME ZONE 'Asia/Kolkata')::int AS y, count(*) "
            "FROM napix_call_log GROUP BY 1, 2 ORDER BY 1, 2"
        )
    ).all()
    responses = session.execute(
        text(
            "SELECT api, extract(year FROM fetched_at AT TIME ZONE 'Asia/Kolkata')::int AS y, count(*), "
            "coalesce(sum(pg_column_size(payload)), 0) FROM napix_responses GROUP BY 1, 2 ORDER BY 1, 2"
        )
    ).all()
    return {
        "call_log": {
            "bytes": int(sizes[0] or 0),
            "rows": sum(int(r[2]) for r in calls),
            "oldest_at": sizes[2].isoformat() if sizes[2] else None,
            "by_api_year": [{"api": r[0], "year": r[1], "rows": int(r[2])} for r in calls],
        },
        "responses": {
            "bytes": int(sizes[1] or 0),
            "rows": sum(int(r[2]) for r in responses),
            "by_api_year": [
                {"api": r[0], "year": r[1], "rows": int(r[2]), "payload_bytes": int(r[3])} for r in responses
            ],
        },
    }
