"""Celery application: beat enqueues the daily and weekly work into `fetch_queue` (services/schedules.py);
the fetching itself is done by `aslms queue-worker`, so the broker only carries a few messages a day. The
`rescore-dirty` entry (every 15 minutes) rescores every case when a matching rule, an office or the scoring
settings changed since the last rescore (design recommend-and-claim, decision 4); a scoring-settings save
also dispatches it at once. `extract-text` (every 5 minutes) extracts the text of pending documents
(orders, uploads) in batches of `TEXT_EXTRACT_BATCH`; an upload also dispatches `extract_document_text` at
once (design documents-uploads, decision 10). The alert jobs (design alerts-notifications, "Jobs"):
`alerts-scan-events` every 5 minutes, `alerts-sweep-dates` hourly at minute 10, `notifications-send` every
2 minutes (also dispatched after a scan or sweep that queued e-mail) and `digests-build` daily at 08:00 IST;
each writes a `job_runs` row with its counters; nothing here calls NAPIX. `sourcetrace-ingest` (every 5 minutes)
sends due court orders and court filings to SourceTrace (design sourcetrace-connector, decisions 14-15): while
the connector is `disabled` or `not_implemented` it returns at once, sends nothing and writes no `job_runs` row.
`dedupe-sweep` (03:00 IST) runs the duplicate rules over every case (design data-load-console, decision 16) and
writes a `job_runs` row with `{merged, needs_review, court_linked}`; it makes no NAPIX call.
Run: `celery -A aslms.jobs.celery_app worker -B --concurrency 1` (the Compose `scheduler` service)."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime

from celery import Celery
from celery.schedules import crontab

from aslms.core.config import get_settings
from aslms.db.session import get_sessionmaker, session_scope
from aslms.domain.ops import JobRun, JobStatus
from aslms.integration.sourcetrace import connector_state, get_connector
from aslms.services import (
    alerts,
    case_dedupe,
    matching,
    notifications,
    schedules,
    sourcetrace_ingest,
    text_extract,
)
from aslms.services.mailer import get_mailer
from aslms.services.storage import LocalStore

log = logging.getLogger(__name__)
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
        "alerts-scan-events": {"task": "aslms.alerts_scan_events", "schedule": crontab(minute="*/5")},
        "alerts-sweep-dates": {"task": "aslms.alerts_sweep_dates", "schedule": crontab(minute=10)},
        "notifications-send": {"task": "aslms.notifications_send", "schedule": crontab(minute="*/2")},
        "digests-build": {"task": "aslms.digests_build", "schedule": crontab(hour=8, minute=0)},
        "sourcetrace-ingest": {"task": "aslms.sourcetrace_ingest", "schedule": crontab(minute="*/5")},
        "dedupe-sweep": {"task": "aslms.dedupe_sweep", "schedule": crontab(hour=3, minute=0)},
        # department discovery (design department-discovery, decision 5): only enqueues; the worker fetches
        "discovery-weekly": {
            "task": "aslms.enqueue_discovery",
            "schedule": crontab(day_of_week="saturday", hour=2, minute=0),
        },
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


@app.task(name="aslms.enqueue_discovery")
def enqueue_discovery() -> dict[str, int]:
    """The weekly discovery sweep: every active term, registration years 2025 to the current year (owner's decision
    of 14 Oct 2026). Only queues `party_search` rows in the discovery lane."""
    from aslms.services import discovery

    with session_scope() as s:
        return discovery.enqueue_weekly(s)


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


@app.task(name="aslms.dedupe_sweep")
def dedupe_sweep() -> dict:
    """Decision 16: merge provisional rows into the row holding their CNR, link the court's duplicates, list the
    rest for review; one `job_runs` row with the counters and one `data_load.dedupe_scan` audit row (system)."""
    from aslms.services.audit import Actor, write_audit

    with session_scope() as s:
        run = JobRun(job="dedupe-sweep", run_date=date.today())
        s.add(run)
        s.flush()
        try:
            report = case_dedupe.sweep(s, actor=Actor.system("dedupe-sweep"))
        except Exception as exc:  # noqa: BLE001 — recorded on the run, then re-raised for the worker log
            run.status, run.error = JobStatus.FAILED, f"{exc.__class__.__name__}: {exc}"[:2000]
            s.flush()
            raise
        counters = report.counts()
        write_audit(
            s,
            Actor.system("dedupe-sweep"),
            "data_load.dedupe_scan",
            "cases",
            None,
            after={**counters, "dry_run": False},
        )
        run.counters = counters
        run.status = JobStatus.SUCCEEDED
        run.finished_at = datetime.now(UTC)
        return counters


# ------------------------------------------------------------------------------------------------ alerts


def _dispatch_sender(counters: dict) -> None:
    """After a scan or sweep that queued e-mail, send at once (best effort; the 2-minute beat is the net)."""
    if counters.get("notifications"):
        try:
            notifications_send.delay()
        except Exception:  # noqa: BLE001 — no broker reachable: the beat entry sends later
            pass


@app.task(name="aslms.alerts_scan_events")
def alerts_scan_events() -> dict:
    """The event scan (design alerts-notifications, decision 2): new events in the window become alerts."""
    with session_scope() as s:
        counters = alerts.scan_events(s, config=alerts.AlertConfig.from_settings(settings))
    _dispatch_sender(counters)
    return counters


@app.task(name="aslms.alerts_sweep_dates")
def alerts_sweep_dates() -> dict:
    """The date sweep (decisions 6, 10, 11): hearing, compliance and request alerts, and the closures."""
    with session_scope() as s:
        counters = alerts.sweep_dates(s, config=alerts.AlertConfig.from_settings(settings))
    _dispatch_sender(counters)
    return counters


@app.task(name="aslms.notifications_send")
def notifications_send() -> dict:
    """Queued and due-for-retry e-mail notifications and digests through the configured mailer."""
    mailer = get_mailer(settings)
    with session_scope() as s:
        return notifications.send_pending(
            s,
            mailer,
            batch=settings.notify_batch,
            max_attempts=settings.notify_max_attempts,
            portal_base_url=settings.portal_base_url,
        )


@app.task(name="aslms.digests_build")
def digests_build() -> dict:
    """The 08:00 IST digest rows, then the sender."""
    with session_scope() as s:
        counters = notifications.build_digests(s, portal_base_url=settings.portal_base_url)
    if counters.get("built"):
        try:
            notifications_send.delay()
        except Exception:  # noqa: BLE001
            pass
    return counters


# ------------------------------------------------------------------------------------------------ SourceTrace


@app.task(name="aslms.sourcetrace_ingest")
def sourcetrace_ingest_task() -> dict:
    """Decision 15: nothing runs until a real connector exists (`{"state": ...}`, no `job_runs` row); then at most
    `SOURCETRACE_BATCH` documents within `SOURCETRACE_RUN_SECONDS`, recorded as a `job_runs` row."""
    state = connector_state(settings)
    if state != "ready":
        if state == "not_implemented":
            log.warning(
                "sourcetrace-ingest: SOURCETRACE_ENABLED is set but no connector exists; nothing sent"
            )
        return {"state": state}
    connector = get_connector(settings)
    if connector is None:
        return {"state": state}
    return sourcetrace_ingest.run(
        get_sessionmaker(),
        connector,
        LocalStore(settings.storage_dir),
        sourcetrace_ingest.IngestConfig.from_settings(settings),
    )
