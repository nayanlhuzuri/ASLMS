"""Celery tasks. Each is a thin wrapper around a service; the task-name prefix picks the queue
(ingest_*, track_*, documents_*, notify_*; everything else → default). See celery_app.py."""

from __future__ import annotations

from datetime import date, timedelta

from aslms.core.logging import get_logger
from aslms.core.time import today_ist
from aslms.db.session import sync_session
from aslms.domain.ops import JobKind
from aslms.integration.factory import napix_source
from aslms.jobs.celery_app import celery_app
from aslms.services import admin, alerts, daily_cycle, ops, orders

log = get_logger(__name__)


@celery_app.task(name="aslms.jobs.tasks.ops_heartbeat")
def ops_heartbeat() -> str:
    log.info("heartbeat")
    return "ok"


@celery_app.task(
    name="aslms.jobs.tasks.ingest_daily_cycle", bind=True, max_retries=2, default_retry_delay=600
)
def ingest_daily_cycle(self, list_date: str | None = None, offset_days: int = 0) -> dict:
    d = date.fromisoformat(list_date) if list_date else today_ist() + timedelta(days=offset_days)
    return daily_cycle.run_daily_cycle(sync_session, d)


@celery_app.task(name="aslms.jobs.tasks.track_status_refresh")
def track_status_refresh() -> dict:
    return daily_cycle.run_status_refresh(sync_session)


@celery_app.task(name="aslms.jobs.tasks.track_full_refresh")
def track_full_refresh() -> dict:
    return daily_cycle.run_full_refresh(sync_session)


@celery_app.task(name="aslms.jobs.tasks.track_discovery")
def track_discovery() -> dict:
    with ops.job(sync_session, JobKind.DISCOVERY) as (run_id, counters):
        built = napix_source(run_id)
        if built is None:
            counters["skipped"] = "NAPIX not configured"
            return dict(counters)
        hc, recorder = built
        with sync_session() as s:
            counters.update(admin.discover(s, hc))
            recorder.flush(s)
        return dict(counters)


@celery_app.task(name="aslms.jobs.tasks.documents_download_orders")
def documents_download_orders() -> dict:
    with ops.job(sync_session, JobKind.ORDER_DOWNLOAD) as (run_id, counters):
        built = napix_source(run_id)
        if built is None:
            counters["skipped"] = "NAPIX not configured"
            return dict(counters)
        hc, recorder = built
        with sync_session() as s:
            counters.update(orders.download_pending(s, hc))
            recorder.flush(s)
        return dict(counters)


@celery_app.task(name="aslms.jobs.tasks.ops_master_sync")
def ops_master_sync() -> dict:
    with ops.job(sync_session, JobKind.MASTER_SYNC) as (run_id, counters):
        built = napix_source(run_id)
        if built is None:
            counters["skipped"] = "NAPIX not configured"
            return dict(counters)
        hc, recorder = built
        with sync_session() as s:
            counters.update(admin.sync_masters(s, hc))
            recorder.flush(s)
        return dict(counters)


@celery_app.task(name="aslms.jobs.tasks.ops_rescore_all")
def ops_rescore_all() -> dict:
    with sync_session() as s:
        return {"rescored": admin.rescore_all(s)}


@celery_app.task(name="aslms.jobs.tasks.notify_alerts")
def notify_alerts() -> dict:
    with ops.job(sync_session, JobKind.NOTIFICATIONS) as (_run_id, counters):
        with sync_session() as s:
            counters["alerts"] = alerts.generate(s)
        with sync_session() as s:
            counters["delivery"] = alerts.deliver_pending(s)
        return dict(counters)


@celery_app.task(name="aslms.jobs.tasks.notify_deliver")
def notify_deliver() -> dict:
    with sync_session() as s:
        return alerts.deliver_pending(s)


@celery_app.task(name="aslms.jobs.tasks.notify_digest")
def notify_digest() -> dict:
    with sync_session() as s:
        return {"digests": alerts.send_digests(s)}


@celery_app.task(name="aslms.jobs.tasks.documents_sourcetrace")
def documents_sourcetrace() -> dict:
    """Phase 2: queue eligible court orders and filings, ingest them, then read period next dates.
    Does nothing until SOURCETRACE_ENABLED is true (the connector is a stub until the API is published)."""
    from aslms.core.config import get_settings
    from aslms.integration.sourcetrace import get_knowledge_service
    from aslms.services import sourcetrace

    if not get_settings().sourcetrace_enabled:
        return {"skipped": "SourceTrace not enabled"}
    ks = get_knowledge_service()
    with sync_session() as s:
        out = {"queued": sourcetrace.mark_candidates(s)}
    with sync_session() as s:
        out["ingest"] = sourcetrace.ingest_pending(s, ks)
    with sync_session() as s:
        out["period_next_dates"] = sourcetrace.read_period_next_dates(s, ks)
    return out
