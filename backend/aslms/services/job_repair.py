"""`job_runs` rows left `running` by a stopped process are marked failed at start-up (design deployment-checklist,
decision 18). Each process repairs only its own jobs, and only rows started before the process itself started, so a
run of another process is never touched. No audit row: `job_runs` is derived housekeeping; the repair is logged.
`fetch_queue` is not touched here (`queue.requeue_stale` re-queues stale rows)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from aslms.domain.ops import JobRun, JobStatus

log = logging.getLogger(__name__)

# `aslms queue-worker` (services/runner.py)
WORKER_JOBS = frozenset({"queue-run"})
# every job name written by the Celery tasks of the `scheduler` service
SCHEDULER_JOBS = frozenset(
    {
        "extract_text",
        "dedupe-sweep",
        "rescore",
        "alerts_events",
        "alerts_dates",
        "notifications_send",
        "digests",
        "sourcetrace_ingest",
        "next_dates_read",
    }
)
# `aslms ops backup-scheduler` (services/backups.py)
BACKUP_JOBS = frozenset({"backup", "restore_check"})
ALL_SETS = {"worker": WORKER_JOBS, "scheduler": SCHEDULER_JOBS, "backup": BACKUP_JOBS}


def repair_interrupted(
    session: Session, jobs: frozenset[str] | set[str], before: datetime, reason: str, *, dry_run: bool = False
) -> int:
    """Marks every `running` row of `jobs` started before `before` as failed with `interrupted: <reason>` appended to
    its error. Returns the number of rows (counted only, with `dry_run`)."""
    if not jobs:
        return 0
    where = (JobRun.status == JobStatus.RUNNING, JobRun.job.in_(sorted(jobs)), JobRun.started_at < before)
    if dry_run:
        return int(session.scalar(select(func.count()).select_from(JobRun).where(*where)) or 0)
    note = f"interrupted: {reason}"[:500]
    result = session.execute(
        update(JobRun)
        .where(*where)
        .values(
            status=JobStatus.FAILED,
            finished_at=func.now(),
            error=func.concat_ws("; ", JobRun.error, note),
        )
        .execution_options(synchronize_session=False)
    )
    n = int(result.rowcount or 0)
    if n:
        log.warning("job_runs repaired: %d interrupted row(s) of %s (%s)", n, ", ".join(sorted(jobs)), reason)
    return n


def repair_at_start(session_factory, jobs: frozenset[str], started_at: datetime | None, who: str) -> int:
    """The start-up call of one process: its own jobs, rows older than its start. Errors are logged, never fatal."""
    started_at = started_at or datetime.now(UTC)
    try:
        with session_factory() as s:
            n = repair_interrupted(s, jobs, started_at, f"{who} restarted")
            s.commit()
            return n
    except Exception as exc:  # noqa: BLE001 — a repair failure must not stop the process
        log.warning("job_runs repair at %s start failed: %s", who, exc.__class__.__name__)
        return 0
