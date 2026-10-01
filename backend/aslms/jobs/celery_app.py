"""Celery application: beat enqueues the daily and weekly work into `fetch_queue` (services/schedules.py);
the fetching itself is done by `aslms queue-worker`, so the broker only carries a few messages a day.
Run: `celery -A aslms.jobs.celery_app worker -B --concurrency 1` (the Compose `scheduler` service)."""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from aslms.core.config import get_settings
from aslms.db.session import session_scope
from aslms.services import schedules

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
