"""What the clock enqueues (the runner does the fetching). Times are IST.

- 06:00 masters sync
- 06:30 cause-list days: yesterday, today and tomorrow (the court publishes the next day's list the evening
        before, and corrects today's during the morning), plus a recheck of today's held lists while
        `CAUSELIST_RECHECK_MORNING` is on
- 18:30 the same three days, plus a recheck of today's and tomorrow's held lists (priority 21, lane daily): Show
        Cause List only, to catch a corrected list re-issued under the same number (design `court-data-freshness`,
        decisions 7, 8 and 14)
- 02:30 a dossier refresh for each disposed case due its monthly refresh in the year after disposal (decision 1)
- 20:00 Current Status for every non-disposed case, in blocks of 500
- Sunday 02:00 a dossier re-fetch for every pending case and a first fetch for every case never fully fetched,
        whatever its status (by CNR, or by `<est_code>|<case number>` without one; design `safety-fixes`, decision
        9), and a retry of order PDFs still not available
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from aslms.core.clock import today_ist
from aslms.domain.documents import DownloadStatus, Order
from aslms.domain.ops import FetchKind, FetchLane, JobRun, JobStatus
from aslms.services import queue
from aslms.services.tracking import enqueue_status_batches, enqueue_weekly_dossier_sweep


def enqueue_masters(session: Session) -> bool:
    return queue.enqueue(session, FetchKind.MASTERS, "all", queue.PRIORITY["masters"], requeue=True)


def enqueue_daily_lists(session: Session, today: date | None = None) -> int:
    today = today or today_ist()
    n = 0
    for d in (today - timedelta(days=1), today, today + timedelta(days=1)):
        if queue.enqueue(
            session,
            FetchKind.CAUSELIST_DAY,
            d.isoformat(),
            queue.PRIORITY["list_today"],
            requeue=True,
            lane=FetchLane.DAILY,
            list_date=d,
        ):
            n += 1
    return n


def enqueue_rechecks(
    session: Session,
    days: list[date],
    *,
    lane: FetchLane = FetchLane.DAILY,
    priority: int | None = None,
    requested_by=None,
) -> int:
    """One `causelist_recheck` row per date (decision 8), `requeue`: a done recheck of the morning runs again in the
    evening. Returns the count pending after the calls.

    A system call (no `requested_by`) revives a done, failed or skipped row `as_new`: an operator's earlier recheck
    (request lane, priority 20, a person) comes back as the system's (daily lane, priority 21, no person), never as a
    request-lane row with nobody behind it. A pending or running row is left as `enqueue` leaves it (an operator's
    pending request keeps its person, lane and priority)."""
    pr = queue.PRIORITY["list_recheck"] if priority is None else priority
    n = 0
    for d in days:
        if queue.enqueue(
            session,
            FetchKind.CAUSELIST_RECHECK,
            d.isoformat(),
            pr,
            requeue=True,
            lane=lane,
            list_date=d,
            requested_by=requested_by,
            as_new=requested_by is None,
        ):
            n += 1
    return n


def enqueue_evening_lists(session: Session, today: date | None = None) -> dict[str, int]:
    """18:30 IST: the three list days, then a recheck of today's and tomorrow's held lists (decision 8)."""
    today = today or today_ist()
    days = enqueue_daily_lists(session, today)
    rechecks = enqueue_rechecks(session, [today, today + timedelta(days=1)])
    return {"days": days, "rechecks": rechecks}


def enqueue_morning_lists(session: Session, today: date | None = None, settings=None) -> dict[str, int]:
    """06:30 IST: the three list days, plus a recheck of today's held lists while `CAUSELIST_RECHECK_MORNING` is on
    (decision 14, owner's answer (a))."""
    from aslms.core.config import get_settings

    cfg = settings or get_settings()
    today = today or today_ist()
    days = enqueue_daily_lists(session, today)
    rechecks = enqueue_rechecks(session, [today]) if cfg.causelist_recheck_morning else 0
    return {"days": days, "rechecks": rechecks}


def run_disposed_refresh(
    session: Session, settings=None, *, today: date | None = None, now: datetime | None = None
) -> dict[str, Any]:
    """The 02:30 IST job (decisions 1-6): `enqueue_disposed_refresh` recorded as one `job_runs` row
    `disposed-refresh` with `{eligible, due, cap, queued}`. A system enqueue: no audit row."""
    from aslms.services.tracking import enqueue_disposed_refresh

    run = JobRun(job="disposed-refresh", run_date=today or today_ist())
    session.add(run)
    session.flush()
    try:
        counters = enqueue_disposed_refresh(session, today, settings, now=now)
    except Exception as exc:  # noqa: BLE001 — recorded on the run, then re-raised for the worker log
        run.status, run.error = JobStatus.FAILED, f"{exc.__class__.__name__}: {exc}"[:2000]
        run.finished_at = datetime.now(UTC)
        session.flush()
        raise
    run.counters = counters
    run.status = JobStatus.SUCCEEDED
    run.finished_at = datetime.now(UTC)
    session.flush()
    return counters


def enqueue_daily_status(session: Session, today: date | None = None) -> int:
    return enqueue_status_batches(session, today or today_ist())


def enqueue_weekly(session: Session) -> dict[str, int]:
    dossiers = enqueue_weekly_dossier_sweep(session)
    retried = session.execute(
        update(Order)
        .where(Order.download_status == DownloadStatus.NOT_AVAILABLE, Order.document_id.is_(None))
        .values(download_status=DownloadStatus.PENDING)
    ).rowcount
    # the next dossier apply re-queues their PDFs; cases without a pending dossier get them queued here
    orders = 0
    from aslms.domain.cases import Case
    from aslms.services.orders import enqueue_order_pdfs

    for case in session.scalars(
        select(Case).where(
            Case.id.in_(
                select(Order.case_id).where(
                    Order.download_status == DownloadStatus.PENDING, Order.document_id.is_(None)
                )
            )
        )
    ).all():
        orders += enqueue_order_pdfs(session, case)
    return {"dossiers": dossiers, "orders_retried": retried or 0, "orders_queued": orders}


# ------------------------------------------------------------------------------------------------ in plain words
# design data-collection-redesign, decision 40: the data-collection entries of `celery_app.beat_schedule` described
# for the Automatic Collection tab (a test keeps the two in step). `beat` is the beat entry, `job` the `job_runs` name
# its task writes (None: the task only queues rows and records no run).

PLAIN_SCHEDULE: tuple[dict[str, Any], ...] = (
    {
        "key": "masters",
        "beat": "masters-daily",
        "when": "06:00",
        "what": "Update the court's reference lists",
        "job": None,
    },
    {
        "key": "lists-morning",
        "beat": "lists-daily",
        "when": "06:30",
        "what": "Fetch yesterday's, today's and tomorrow's cause lists, and check today's again for corrections",
        "job": None,
    },
    {
        "key": "lists-evening",
        "beat": "lists-evening",
        "when": "18:30",
        "what": "Fetch the three days' cause lists again and check today's and tomorrow's for corrections",
        "job": None,
    },
    {
        "key": "status",
        "beat": "status-daily",
        "when": "20:00",
        "what": "Check the status of every case that is not disposed",
        "job": None,
    },
    {
        "key": "disposed-refresh",
        "beat": "disposed-refresh",
        "when": "02:30",
        "what": "Refresh cases disposed in the last year, monthly",
        "job": "disposed-refresh",
    },
    {
        "key": "dedupe",
        "beat": "dedupe-sweep",
        "when": "03:00",
        "what": "Look for duplicate cases",
        "job": "dedupe-sweep",
    },
    {
        "key": "purge",
        "beat": "napix-log-purge",
        "when": "03:45",
        "what": "Remove court call records older than 2 years",
        "job": "napix-log-purge",
    },
    {
        "key": "weekly",
        "beat": "weekly-sweep",
        "when": "Sundays 02:00",
        "what": "Refresh the details of every case not fully fetched",
        "job": None,
    },
    {
        "key": "discovery",
        "beat": "discovery-weekly",
        "when": "Saturdays 02:00",
        "what": "Search the court by department names",
        "job": None,
    },
    {
        "key": "load",
        "beat": None,
        "when": "Always",
        "what": "Past-months collection, in the calls left over",
        "job": None,
    },
)

# the beat entries that are not data collection (scoring, text, alerts, mail, the Case Assistant, search rows)
NOT_DATA_COLLECTION: frozenset[str] = frozenset(
    {
        "rescore-dirty",
        "extract-text",
        "next-dates-read",
        "alerts-scan-events",
        "alerts-sweep-dates",
        "notifications-send",
        "digests-build",
        "sourcetrace-ingest",
        "store-search-rows",
    }
)


def _last_run(session: Session, job: str) -> JobRun | None:
    return session.scalar(select(JobRun).where(JobRun.job == job).order_by(JobRun.started_at.desc()).limit(1))


def schedule_view(session: Session, settings=None, now: datetime | None = None) -> dict[str, Any]:
    """`GET /admin/data-load/schedule`: each plain entry with its last run where the task records one (`last_run_at`,
    `result` the run's status, else None: "Not Recorded"), its facts (the disposed refresh's cases in their first
    year and due now; the purge's rows removed; the duplicate counts), and the daily cycle of the last 7 days. Reads
    only."""
    from aslms.core.config import get_settings
    from aslms.services import data_health, tracking
    from aslms.services.audit_search import to_ist

    cfg = settings or get_settings()
    now = now or datetime.now(UTC)
    today = today_ist(now)
    entries = []
    for item in PLAIN_SCHEDULE:
        run = _last_run(session, item["job"]) if item["job"] else None
        facts: dict[str, Any] = {}
        if item["key"] == "disposed-refresh":
            facts = {
                "eligible": tracking.disposed_eligible_count(
                    session, today, keep_days=cfg.disposed_refresh_days
                ),
                "due_now": tracking.disposed_due_count(
                    session,
                    today,
                    keep_days=cfg.disposed_refresh_days,
                    every_days=cfg.disposed_refresh_every_days,
                    now=now,
                ),
            }
        elif run is not None and item["key"] == "purge":
            facts = {"deleted": (run.counters or {}).get("deleted")}
        elif run is not None and item["key"] == "dedupe":
            facts = {k: v for k, v in (run.counters or {}).items() if isinstance(v, int)}
        entries.append(
            {
                "key": item["key"],
                "when": item["when"],
                "what": item["what"],
                "last_run_at": to_ist(run.started_at) if run is not None else None,
                "result": getattr(run.status, "value", run.status) if run is not None else None,
                "facts": facts,
            }
        )
    return {"entries": entries, "daily_cycle": data_health.daily_cycle(session, now, back=6, forward=0)}
