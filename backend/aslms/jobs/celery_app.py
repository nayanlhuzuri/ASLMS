"""Celery application. Queues (ground rule 11 — these names MUST match the `-Q` flags in docker-compose.yml):
  ingest     — daily cycle: cause lists, entries, case resolution, scoring
  track      — current-status and full refreshes of tracked cases
  documents  — order downloads, virus scans, text extraction, SourceTrace ingestion (Phase 2)
  notify     — e-mail / SMS / digest delivery
  default    — everything else (master sync, housekeeping)
Task names are routed by prefix: aslms.jobs.tasks.<queue>_<name>."""

from __future__ import annotations

from celery import Celery

from aslms.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "aslms", broker=settings.redis_url, backend=settings.redis_url, include=["aslms.jobs.tasks"]
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone=settings.timezone,
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_time_limit=3600,
    task_default_queue="default",
    task_routes={
        "aslms.jobs.tasks.ingest_*": {"queue": "ingest"},
        "aslms.jobs.tasks.track_*": {"queue": "track"},
        "aslms.jobs.tasks.documents_*": {"queue": "documents"},
        "aslms.jobs.tasks.notify_*": {"queue": "notify"},
    },
    beat_schedule={},  # filled in aslms/jobs/schedules.py once the daily cycle exists
)

from aslms.jobs.schedules import BEAT_SCHEDULE  # noqa: E402

celery_app.conf.beat_schedule = BEAT_SCHEDULE
