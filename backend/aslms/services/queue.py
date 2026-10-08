"""The resumable fetch queue (`fetch_queue`): every unit of NAPIX work is a row, claimed with
`FOR UPDATE SKIP LOCKED`, so any number of workers can pull and nothing is lost when one dies (a `running` row
older than the stale limit is re-queued). Kinds and the meaning of `ref`:

- `masters`        ref `all`
- `causelist_day`  ref `YYYY-MM-DD`
- `dossier`        ref `<CNR>`, or `<est_code>|<case number as printed>` for a listed case without a CNR
                   (resolved through Search by Case Number first)
- `status_batch`   ref `<YYYY-MM-DD>:<n>` (the n-th batch of up to 500 non-disposed CNRs for that day)
- `order_pdf`      ref `<CNR>|<order_no>|<YYYY-MM-DD>`

Priorities (lower runs first): masters 10, today's and tomorrow's lists 20, status batches 30, new dossiers 40,
dossier re-fetches 50, historical list days 60, order PDFs 80."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from aslms.domain.ops import FetchKind, FetchQueueItem, FetchStatus

PRIORITY = {
    "masters": 10,
    "list_today": 20,
    "status": 30,
    "dossier_new": 40,
    "dossier_refetch": 50,
    "list_history": 60,
    "order_pdf": 80,
}
MAX_ATTEMPTS = 5
STALE_RUNNING = timedelta(minutes=30)


def enqueue(
    session: Session,
    kind: FetchKind,
    ref: str,
    priority: int,
    *,
    not_before: datetime | None = None,
    requeue: bool = False,
) -> bool:
    """Insert or revive a row. Without `requeue`, a `done` row stays done; a `failed` or `skipped` row is
    revived; a `pending` row keeps the better (lower) priority. Returns True when the row is pending after
    the call."""
    row = session.execute(
        text(
            """
            INSERT INTO fetch_queue (kind, ref, priority, not_before)
            VALUES (CAST(:kind AS fetch_kind), :ref, :priority, :not_before)
            ON CONFLICT (kind, ref) DO UPDATE SET
                priority = LEAST(fetch_queue.priority, EXCLUDED.priority),
                not_before = CASE WHEN fetch_queue.status = 'pending' THEN fetch_queue.not_before ELSE EXCLUDED.not_before END,
                status = CASE
                    WHEN fetch_queue.status IN ('failed', 'skipped') THEN 'pending'::fetch_queue_status
                    WHEN fetch_queue.status = 'done' AND :requeue THEN 'pending'::fetch_queue_status
                    ELSE fetch_queue.status END,
                attempts = CASE WHEN fetch_queue.status IN ('failed', 'skipped') OR (fetch_queue.status = 'done' AND :requeue)
                    THEN 0 ELSE fetch_queue.attempts END,
                last_error = NULL
            RETURNING status
            """
        ),
        {"kind": kind.value, "ref": ref, "priority": priority, "not_before": not_before, "requeue": requeue},
    ).scalar_one()
    return row == "pending"


def claim(session: Session, kinds: list[FetchKind] | None = None) -> FetchQueueItem | None:
    """The highest-priority runnable row, marked running. Returns None when nothing is runnable."""
    kind_filter = "AND kind = ANY(CAST(:kinds AS fetch_kind[]))" if kinds else ""
    row = session.execute(
        text(
            f"""
            UPDATE fetch_queue SET status = 'running', started_at = now(), attempts = attempts + 1
            WHERE id = (
                SELECT id FROM fetch_queue
                WHERE status = 'pending' AND (not_before IS NULL OR not_before <= now()) {kind_filter}
                ORDER BY priority, created_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING id
            """
        ),
        {"kinds": [k.value for k in kinds] if kinds else None},
    ).first()
    if row is None:
        return None
    return session.get(FetchQueueItem, row[0])


def complete(
    session: Session, item: FetchQueueItem, result: dict[str, Any] | None = None, *, skipped: bool = False
) -> None:
    item.status = FetchStatus.SKIPPED if skipped else FetchStatus.DONE
    item.finished_at = datetime.now(UTC)
    item.result = result
    item.last_error = None
    session.flush()


def fail(session: Session, item: FetchQueueItem, error: str, *, retry_in: timedelta | None = None) -> None:
    """Back to pending with a delay while attempts remain; failed after MAX_ATTEMPTS."""
    item.last_error = error[:2000]
    item.finished_at = datetime.now(UTC)
    if item.attempts >= MAX_ATTEMPTS:
        item.status = FetchStatus.FAILED
    else:
        item.status = FetchStatus.PENDING
        item.not_before = datetime.now(UTC) + (retry_in or timedelta(minutes=5 * item.attempts))
    session.flush()


def requeue_stale(session: Session) -> int:
    n = session.execute(
        text(
            """
            UPDATE fetch_queue SET status = 'pending', last_error = COALESCE(last_error, 'worker lost')
            WHERE status = 'running' AND started_at < now() - CAST(:age AS interval)
            """
        ),
        {"age": f"{int(STALE_RUNNING.total_seconds())} seconds"},
    ).rowcount
    return n or 0


def get_state(session: Session, kind: FetchKind, ref: str) -> FetchQueueItem | None:
    """The row of (kind, ref) as stored now (re-read: `enqueue` writes through SQL), or None."""
    return session.scalar(
        select(FetchQueueItem)
        .where(FetchQueueItem.kind == kind, FetchQueueItem.ref == ref)
        .execution_options(populate_existing=True)
    )


def status_counts(session: Session) -> list[tuple[str, str, int]]:
    rows = session.execute(
        text("SELECT kind::text, status::text, count(*) FROM fetch_queue GROUP BY 1, 2 ORDER BY 1, 2")
    ).all()
    return [(k, s, int(c)) for k, s, c in rows]


def pending_count(session: Session, kind: FetchKind | None = None) -> int:
    stmt = select(FetchQueueItem).where(FetchQueueItem.status == FetchStatus.PENDING)
    if kind:
        stmt = stmt.where(FetchQueueItem.kind == kind)
    return len(session.scalars(stmt).all())


def item_id(item: FetchQueueItem) -> uuid.UUID:
    return item.id
