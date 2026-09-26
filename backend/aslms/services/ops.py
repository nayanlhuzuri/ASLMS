"""Job runs and source failures (ground rule 7: failures are recorded, never lost)."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aslms.core.logging import get_logger
from aslms.core.time import now_utc
from aslms.domain.events import EventType
from aslms.domain.ops import FailureKind, JobKind, JobRun, JobStatus, SourceFailure
from aslms.services import events

log = get_logger(__name__)


def start_job(session: Session, job: JobKind, run_date: date | None = None) -> JobRun:
    run = JobRun(job=job, run_date=run_date, started_at=now_utc(), status=JobStatus.RUNNING, counters={})
    session.add(run)
    session.flush()
    return run


def finish_job(
    session: Session,
    run: JobRun,
    counters: dict[str, Any],
    *,
    error: str | None = None,
    partial: bool = False,
) -> None:
    run.finished_at = now_utc()
    run.counters = {k: v for k, v in counters.items()}
    run.error = error
    run.status = (
        JobStatus.FAILED
        if error and not partial
        else JobStatus.PARTIAL
        if (error or partial)
        else JobStatus.SUCCEEDED
    )


def record_failure(session: Session, kind: FailureKind, ref: str, error: str) -> SourceFailure:
    now = now_utc()
    f = session.scalar(
        select(SourceFailure).where(
            SourceFailure.kind == kind, SourceFailure.ref == ref[:300], SourceFailure.resolved_at.is_(None)
        )
    )
    if f:
        f.error, f.last_seen, f.attempts = error[:4000], now, f.attempts + 1
    else:
        f = SourceFailure(
            kind=kind, ref=ref[:300], error=error[:4000], first_seen=now, last_seen=now, attempts=1
        )
        session.add(f)
        session.flush()
        events.emit(
            session,
            EventType.SOURCE_FAILED,
            f"source_failed:{kind.value}:{ref}:{now:%Y%m%d}",
            payload={"kind": kind.value, "ref": ref, "error": error[:500]},
        )
    log.warning("source failure recorded", kind=kind.value, ref=ref, error=error[:200])
    return f


def resolve_failure(session: Session, kind: FailureKind, ref: str) -> None:
    f = session.scalar(
        select(SourceFailure).where(
            SourceFailure.kind == kind, SourceFailure.ref == ref[:300], SourceFailure.resolved_at.is_(None)
        )
    )
    if f:
        f.resolved_at = now_utc()


@contextmanager
def job(session_factory, kind: JobKind, run_date: date | None = None):
    """Opens a JobRun in its own transaction and closes it with the counters the body fills in.
    Usage: `with ops.job(sync_session, JobKind.DAILY_CYCLE, d) as (run_id, counters): ...`"""
    with session_factory() as s:
        run = start_job(s, kind, run_date)
        run_id: uuid.UUID = run.id
    counters: dict[str, Any] = {}
    error: str | None = None
    try:
        yield run_id, counters
    except Exception as e:
        error = f"{type(e).__name__}: {e}"[:2000]
        raise
    finally:
        with session_factory() as s:
            run = s.get(JobRun, run_id)
            finish_job(s, run, counters, error=error, partial=bool(counters.get("failures")))
