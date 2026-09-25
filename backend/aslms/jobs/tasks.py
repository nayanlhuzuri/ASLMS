"""Celery tasks. Each task is a thin wrapper: open a sync session, call a service, record a JobRun.
Naming convention decides the queue (see celery_app.py)."""

from __future__ import annotations

from aslms.core.logging import get_logger
from aslms.jobs.celery_app import celery_app

log = get_logger(__name__)


@celery_app.task(name="aslms.jobs.tasks.ops_heartbeat")
def ops_heartbeat() -> str:
    """Proves beat → broker → worker is wired. Replaced by real housekeeping later."""
    log.info("heartbeat")
    return "ok"
