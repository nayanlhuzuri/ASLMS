"""What the clock enqueues (the runner does the fetching). Times are IST.

- 06:00 masters sync
- 06:30 cause-list days: yesterday, today and tomorrow (the court publishes the next day's list the evening
        before, and corrects today's during the morning)
- 20:00 Current Status for every non-disposed case, in blocks of 500
- Sunday 02:00 a dossier re-fetch for every pending case, and a retry of order PDFs still not available
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from aslms.domain.documents import DownloadStatus, Order
from aslms.domain.ops import FetchKind, FetchLane
from aslms.services import queue
from aslms.services.tracking import enqueue_status_batches, enqueue_weekly_dossier_sweep


def enqueue_masters(session: Session) -> bool:
    return queue.enqueue(session, FetchKind.MASTERS, "all", queue.PRIORITY["masters"], requeue=True)


def enqueue_daily_lists(session: Session, today: date | None = None) -> int:
    today = today or date.today()
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


def enqueue_daily_status(session: Session, today: date | None = None) -> int:
    return enqueue_status_batches(session, today or date.today())


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
