"""Celery application: beat enqueues the daily and weekly work into `fetch_queue` (services/schedules.py);
the fetching itself is done by `aslms queue-worker`, so the broker only carries a few messages a day. The
`rescore-dirty` entry (every 15 minutes) rescores every case when a matching rule, an office or the scoring
settings changed since the last rescore (design recommend-and-claim, decision 4); a scoring-settings save
also dispatches it at once. `extract-text` (every 5 minutes) extracts the text of pending documents
(orders, uploads) in batches of `TEXT_EXTRACT_BATCH`; an upload also dispatches `extract_document_text` at
once (design documents-uploads, decision 10). No NAPIX call.
Run: `celery -A aslms.jobs.celery_app worker -B --concurrency 1` (the Compose `scheduler` service)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from celery import Celery
from celery.schedules import crontab

from aslms.core.config import get_settings
from aslms.db.session import get_sessionmaker, session_scope
from aslms.domain.ops import JobRun, JobStatus
from aslms.services import matching, schedules, text_extract
from aslms.services.storage import LocalStore

settings = get_settings()
app = Celery("aslms", broker=settings.redis_url or "redis://localhost:6379/0")
app.conf.update(
    timezone="Asia/Kolkata",
    enable_utc=True,
    task_default_queue="aslms",
    worker_hijack_root_logger=False,
    beat_schedule={
        "masters-daily": {"task": "aslms.enqueue_masters", "schedule": crontab(hour=6, minute=0)},
        "lists-daily": {"task": "aslms.enqueue_daily_lists", "schedule": crontab(hour=6, minute=30)},
        "lists-evening": {"task": "aslms.enqueue_daily_lists", "schedule": crontab(hour=18, minute=30)},
        "status-daily": {"task": "aslms.enqueue_daily_status", "schedule": crontab(hour=20, minute=0)},
        "weekly-sweep": {
            "task": "aslms.enqueue_weekly",
            "schedule": crontab(day_of_week="sunday", hour=2, minute=0),
        },
        "rescore-dirty": {"task": "aslms.rescore_if_dirty", "schedule": crontab(minute="*/15")},
        "extract-text": {"task": "aslms.extract_pending_text", "schedule": crontab(minute="*/5")},
    },
)


@app.task(name="aslms.enqueue_masters")
def enqueue_masters() -> bool:
    with session_scope() as s:
        return schedules.enqueue_masters(s)


@app.task(name="aslms.enqueue_daily_lists")
def enqueue_daily_lists() -> int:
    with session_scope() as s:
        return schedules.enqueue_daily_lists(s)


@app.task(name="aslms.enqueue_daily_status")
def enqueue_daily_status() -> int:
    with session_scope() as s:
        return schedules.enqueue_daily_status(s)


@app.task(name="aslms.enqueue_weekly")
def enqueue_weekly() -> dict[str, int]:
    with session_scope() as s:
        return schedules.enqueue_weekly(s)


@app.task(name="aslms.rescore_if_dirty")
def rescore_if_dirty() -> dict | None:
    """Rescores every case when a rule, an office or the scoring settings changed since the last succeeded
    `rescore` run; None when nothing changed."""
    report = matching.rescore_if_dirty(get_sessionmaker())
    return report.as_dict() if report is not None else None


@app.task(name="aslms.extract_pending_text")
def extract_pending_text() -> dict:
    """A batch of pending documents (`FOR UPDATE SKIP LOCKED`), recorded as a `job_runs` row."""
    store = LocalStore(settings.storage_dir)
    with session_scope() as s:
        run = JobRun(job="extract_text", run_date=date.today())
        s.add(run)
        s.flush()
        try:
            counters = text_extract.extract_pending(s, store, batch=settings.text_extract_batch)
        except Exception as exc:  # noqa: BLE001 — recorded on the run, then re-raised for the worker log
            run.status, run.error = JobStatus.FAILED, f"{exc.__class__.__name__}: {exc}"[:2000]
            s.flush()
            raise
        run.counters = counters
        run.status = JobStatus.PARTIAL if counters.get("failed") else JobStatus.SUCCEEDED
        run.finished_at = datetime.now(UTC)
        return counters


@app.task(name="aslms.extract_document_text")
def extract_document_text(document_id: str) -> dict:
    """One document, dispatched after an upload commits (best effort; the sweep is the safety net)."""
    store = LocalStore(settings.storage_dir)
    with session_scope() as s:
        return text_extract.extract_pending(s, store, batch=1, document_id=uuid.UUID(document_id))
