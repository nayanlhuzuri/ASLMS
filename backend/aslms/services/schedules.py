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
