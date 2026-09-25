"""Beat schedule (IST). Entries are added as the tasks they call are built:
  daily cycle for the next cause-list date the evening before (lists are usually up by ~18:30) and again in
  the morning for supplementary lists; status refresh daily; full refresh weekly; notifications at 08:00.
Confirm the timings after the live NAPIX test (decisions log)."""

from __future__ import annotations

from celery.schedules import crontab

BEAT_SCHEDULE: dict[str, dict] = {
    "ops-heartbeat": {"task": "aslms.jobs.tasks.ops_heartbeat", "schedule": crontab(minute="*/30")},
}
