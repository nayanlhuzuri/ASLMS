"""Beat schedule (Asia/Kolkata). Timings follow the plan's daily cycle and should be confirmed after the live
NAPIX test (decisions log):
  18:30, 20:30, 22:30   daily cycle for tomorrow (lists are usually published by early evening)
  06:15, 08:15, 09:15   daily cycle for today (supplementary lists arrive in the morning)
  05:30                 Current Status for all tracked cases
  Sunday 02:00          full CNR refresh of tracked cases (weekly)
  every 2 h             order downloads; every 15 min notification delivery
  07:30                 alerts; 08:00 daily digest
  1st of month 03:00    NAPIX masters; Saturday 03:00 department discovery"""

from __future__ import annotations

from celery.schedules import crontab

BEAT_SCHEDULE: dict[str, dict] = {
    "daily-cycle-tomorrow": {
        "task": "aslms.jobs.tasks.ingest_daily_cycle",
        "schedule": crontab(hour="18,20,22", minute="30"),
        "kwargs": {"offset_days": 1},
    },
    "daily-cycle-today": {
        "task": "aslms.jobs.tasks.ingest_daily_cycle",
        "schedule": crontab(hour="6,8,9", minute="15"),
        "kwargs": {"offset_days": 0},
    },
    "status-refresh": {
        "task": "aslms.jobs.tasks.track_status_refresh",
        "schedule": crontab(hour="5", minute="30"),
    },
    "full-refresh-weekly": {
        "task": "aslms.jobs.tasks.track_full_refresh",
        "schedule": crontab(day_of_week="sun", hour="2", minute="0"),
    },
    "order-downloads": {
        "task": "aslms.jobs.tasks.documents_download_orders",
        "schedule": crontab(minute="10", hour="*/2"),
    },
    "alerts": {"task": "aslms.jobs.tasks.notify_alerts", "schedule": crontab(hour="7", minute="30")},
    "deliver": {"task": "aslms.jobs.tasks.notify_deliver", "schedule": crontab(minute="*/15")},
    "digest": {"task": "aslms.jobs.tasks.notify_digest", "schedule": crontab(hour="8", minute="0")},
    "masters-monthly": {
        "task": "aslms.jobs.tasks.ops_master_sync",
        "schedule": crontab(day_of_month="1", hour="3", minute="0"),
    },
    "discovery-weekly": {
        "task": "aslms.jobs.tasks.track_discovery",
        "schedule": crontab(day_of_week="sat", hour="3", minute="0"),
    },
    "heartbeat": {"task": "aslms.jobs.tasks.ops_heartbeat", "schedule": crontab(minute="*/30")},
}
