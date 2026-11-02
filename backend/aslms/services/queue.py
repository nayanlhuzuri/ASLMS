"""The resumable fetch queue (`fetch_queue`): every unit of NAPIX work is a row, claimed with
`FOR UPDATE SKIP LOCKED`, so any number of workers can pull and nothing is lost when one dies (a `running` row
older than the stale limit is re-queued). Kinds and the meaning of `ref`:

- `masters`        ref `all`
- `causelist_day`  ref `YYYY-MM-DD`
- `dossier`        ref `<CNR>`, or `<est_code>|<case number as printed>` for a listed case without a CNR
                   (resolved through Search by Case Number first)
- `status_batch`   ref `<YYYY-MM-DD>:<n>` (the n-th batch of up to 500 non-disposed CNRs for that day)
- `order_pdf`      ref `<CNR>|<order_no>|<YYYY-MM-DD>`
- `party_search`   ref `<est_code>|P|<reg_year>|<term>` (department discovery)
- `causelist_recheck` ref `YYYY-MM-DD`: Show Cause List again for the held NAPIX lists of the date, to catch a
                   corrected list re-issued under the same number (design `court-data-freshness`, decisions 7-8)
- `search_rows`    ref `<napix_responses.id>`: the background storing of a capped advocate search's rows; no NAPIX
                   call, claimed only by the Celery task `aslms.store_search_rows` (`LOCAL_KINDS`; design
                   `safety-fixes`, decision 13)

A request's rows carry its id (design `data-collection-redesign`, decision 32; row 174 review): `result.request_ids` is
the JSON list of the requests (their `audit_log.id`) whose run the row's pending, running or latest run is. `enqueue`
with `request_ids` sets them on an inserted or revived row and adds them to a pending or running one; a revived row
without them loses them (later work of someone else); `complete` keeps them next to the run's result and `fail` leaves
them, so a retry stays the request's. What a row spawns takes its tags (`from_parent`, read when it spawns).

A failed attempt goes back to `pending` on the ladder `RETRY_LADDER` (10 min, 1 h, 6 h, 24 h, 72 h) and the row is
`failed` after the sixth failed attempt; a `failed` row is mirrored into `source_failures` as `fetch_<kind>` and that
failure resolved when the row later ends `done` or `skipped` (design `safety-fixes`, decisions 6 and 10).

Every row carries a lane (design `data-load-console`, decision 1): `request` (a person asked), `daily` (the daily
cycle) or `load` (the backdated load), in that order of precedence; a row asked by two lanes keeps the higher one
and the better priority. `list_date` is the cause-list date whose loading queued the row, inherited by what it
spawns. `claim` skips `load` rows while the current `data_load_settings` version is paused (decision 2). A `request` row
carries the person who asked for its pending run in `requested_by` (design `napix-window`, decision 10).

Priorities (lower runs first): a person's "now" requests 3 (one case) and 5 (bulk), outside the reserve bands
(design `data-collection-redesign`, decision 24); masters 10; yesterday's, today's and tomorrow's lists 20; the
evening rechecks of held lists 21; a missing day older than yesterday within `CAUSELIST_CATCHUP_DAYS`, queued by the
catch-up or the gap sweep, 22 (design `causelist-day-gap-sweep`, decision 3); status batches and a person's requests
30; the daily cycle's new dossiers and a person's order PDFs 40; the backdated load 41-46 by the preset and the period
brought forward, and discovery 41-43 (`services/load_policy.py`); the weekly dossier sweep 50; the monthly dossiers of
cases disposed within a year 55 (design `court-data-freshness`, decision 2); live-case order PDFs of the daily, load
and discovery lanes 60, after every detail kind (owner, 24 Oct 2026: case details first, order PDFs later);
disposed-case order PDFs 80."""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from aslms.domain.ops import FetchKind, FetchLane, FetchQueueItem, FetchStatus
from aslms.services import source_failures
from aslms.services.load_policy import NOW_BULK, QueueOrigin, now_priority_of

PRIORITY = {
    "masters": 10,
    "list_today": 20,
    "list_recheck": 21,
    "list_catchup": 22,
    "status": 30,
    "request": 30,
    "dossier_new": 40,
    "order_pdf_live": 60,
    "dossier_refetch": 50,
    "dossier_disposed": 55,
    "order_pdf": 80,
}
# design safety-fixes, decision 6: after the n-th failed attempt the row waits RETRY_LADDER[n-1]; failed after the 6th
RETRY_LADDER = (
    timedelta(minutes=10),
    timedelta(hours=1),
    timedelta(hours=6),
    timedelta(hours=24),
    timedelta(hours=72),
)
MAX_ATTEMPTS = len(RETRY_LADDER) + 1
# kinds that make no NAPIX call: claimed only when named (the Celery task), never by the runner's unnamed claim
LOCAL_KINDS = frozenset({FetchKind.SEARCH_ROWS})
STALE_RUNNING = timedelta(minutes=30)


def enqueue(
    session: Session,
    kind: FetchKind,
    ref: str,
    priority: int,
    *,
    not_before: datetime | None = None,
    requeue: bool = False,
    lane: FetchLane = FetchLane.DAILY,
    list_date: date | None = None,
    requested_by: uuid.UUID | None = None,
    as_new: bool = False,
    request_ids: list[str] | tuple[str, ...] | None = None,
) -> bool:
    """Insert or revive a row. Without `requeue`, a `done` row stays done; a `failed` or `skipped` row is
    revived; a `pending` row keeps the better (lower) priority. A pending or revived row takes the
    higher-precedence lane (`LEAST` over the enum: request < daily < load); `list_date` is kept once set.
    `requested_by` (decision 10 of `napix-window`): an inserted, revived or re-queued row takes the caller's value
    (NULL for system callers); a pending row keeps its first person (`COALESCE`), as does a running request row. Only
    the request lane carries a person: a person with another lane raises `ValueError` before any SQL.
    `not_before` (design `safety-fixes`, decision 7): a pending row keeps its own, except that a `request`-lane call
    on a pending row waiting in the future gives it the caller's (NULL = now); attempts and the ladder are kept.
    `as_new` (design `court-data-freshness`, decision 2): a revived row (`done` with `requeue`, `failed`, `skipped`)
    takes the caller's priority and lane and a fresh `created_at`, as an inserted row would, instead of keeping the
    better priority and its first queueing time; a pending or running row is treated as without it.
    A finished row's "now" priority (5 or less, design `data-collection-redesign`, decision 24) ends with the request
    that set it: a revived row at a now priority is revived as with `as_new`, so later system work takes its own
    priority and lane instead of running as a person's "now" request outside the reserves.
    `request_ids` (row 174 review): the requests this call is made for. An inserted or revived row takes exactly them
    (none for system work, so a later run of someone else is never a finished request's item); a pending or running
    row adds them to its own; a row left `done` keeps its own.
    Returns True when the row is pending after the call."""
    if requested_by is not None and FetchLane(lane) != FetchLane.REQUEST:
        raise ValueError("only a request-lane row carries the person who asked for it")
    row = session.execute(
        text(
            """
            INSERT INTO fetch_queue (kind, ref, priority, not_before, lane, list_date, requested_by, result)
            VALUES (CAST(:kind AS fetch_kind), :ref, :priority, :not_before, CAST(:lane AS fetch_lane), :list_date,
                CAST(:requested_by AS uuid),
                CASE WHEN CAST(:tags AS jsonb) IS NULL THEN NULL
                     ELSE jsonb_build_object('request_ids', CAST(:tags AS jsonb)) END)
            ON CONFLICT (kind, ref) DO UPDATE SET
                result = CASE
                    WHEN fetch_queue.status IN ('failed', 'skipped') OR (fetch_queue.status = 'done' AND :requeue)
                    THEN CASE WHEN CAST(:tags AS jsonb) IS NULL THEN fetch_queue.result - 'request_ids'
                              ELSE COALESCE(fetch_queue.result, '{}'::jsonb)
                                   || jsonb_build_object('request_ids', CAST(:tags AS jsonb)) END
                    WHEN fetch_queue.status IN ('pending', 'running') AND CAST(:tags AS jsonb) IS NOT NULL
                    THEN COALESCE(fetch_queue.result, '{}'::jsonb) || jsonb_build_object('request_ids', (
                        SELECT jsonb_agg(DISTINCT t) FROM jsonb_array_elements(
                            COALESCE(fetch_queue.result -> 'request_ids', '[]'::jsonb) || CAST(:tags AS jsonb)) t))
                    ELSE fetch_queue.result END,
                priority = CASE
                    WHEN (:as_new OR fetch_queue.priority <= :now_max) AND (fetch_queue.status IN ('failed', 'skipped')
                        OR (fetch_queue.status = 'done' AND :requeue))
                    THEN EXCLUDED.priority
                    ELSE LEAST(fetch_queue.priority, EXCLUDED.priority) END,
                created_at = CASE
                    WHEN (:as_new OR fetch_queue.priority <= :now_max) AND (fetch_queue.status IN ('failed', 'skipped')
                        OR (fetch_queue.status = 'done' AND :requeue))
                    THEN now() ELSE fetch_queue.created_at END,
                lane = CASE
                    WHEN (:as_new OR fetch_queue.priority <= :now_max) AND (fetch_queue.status IN ('failed', 'skipped')
                        OR (fetch_queue.status = 'done' AND :requeue))
                    THEN EXCLUDED.lane
                    WHEN fetch_queue.status IN ('pending', 'failed', 'skipped')
                        OR (fetch_queue.status = 'done' AND :requeue)
                    THEN LEAST(fetch_queue.lane, EXCLUDED.lane) ELSE fetch_queue.lane END,
                list_date = COALESCE(fetch_queue.list_date, EXCLUDED.list_date),
                requested_by = CASE
                    WHEN fetch_queue.status IN ('failed', 'skipped')
                        OR (fetch_queue.status = 'done' AND :requeue)
                    THEN EXCLUDED.requested_by
                    WHEN fetch_queue.status = 'pending'
                        OR (fetch_queue.status = 'running' AND fetch_queue.lane = 'request')
                    THEN COALESCE(fetch_queue.requested_by, EXCLUDED.requested_by)
                    ELSE fetch_queue.requested_by END,
                not_before = CASE
                    WHEN fetch_queue.status = 'pending' AND :request_lane AND fetch_queue.not_before > now()
                    THEN EXCLUDED.not_before
                    WHEN fetch_queue.status = 'pending' THEN fetch_queue.not_before
                    ELSE EXCLUDED.not_before END,
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
        {
            "kind": kind.value,
            "ref": ref,
            "priority": priority,
            "not_before": not_before,
            "requeue": requeue,
            "lane": FetchLane(lane).value,
            "list_date": list_date,
            "requested_by": requested_by,
            "request_lane": FetchLane(lane) == FetchLane.REQUEST,
            "as_new": as_new,
            "now_max": NOW_BULK,
            "tags": json.dumps([str(t) for t in request_ids]) if request_ids else None,
        },
    ).scalar_one()
    return row == "pending"


PAUSE_CLAUSE = (
    "AND (lane <> 'load' OR NOT EXISTS (SELECT 1 FROM data_load_settings WHERE is_current AND paused))"
)


def _filters(
    kinds: list[FetchKind] | None, lanes: list[FetchLane] | None, max_priority: int | None = None
) -> tuple[str, dict[str, Any]]:
    # without named kinds the local kinds are left out (design safety-fixes, decision 13): the runner never takes them
    kind_filter = (
        "AND kind = ANY(CAST(:kinds AS fetch_kind[]))"
        if kinds
        else "AND NOT (kind = ANY(CAST(:local AS fetch_kind[])))"
    )
    lane_filter = "AND lane = ANY(CAST(:lanes AS fetch_lane[]))" if lanes else ""
    priority_filter = "AND priority <= :max_priority" if max_priority is not None else ""
    where = (
        "status = 'pending' AND (not_before IS NULL OR not_before <= now()) "
        f"{priority_filter} {kind_filter} {lane_filter} {PAUSE_CLAUSE}"
    )
    params = {
        "max_priority": max_priority,
        "kinds": [k.value for k in kinds] if kinds else None,
        "local": sorted(k.value for k in LOCAL_KINDS),
        "lanes": [FetchLane(x).value for x in lanes] if lanes else None,
    }
    return where, params


def has_runnable(
    session: Session, kinds: list[FetchKind] | None = None, lanes: list[FetchLane] | None = None
) -> bool:
    """Whether `claim` would find a row (its conditions and pause clause), without locking or claiming: the runner
    probes the window only when work is waiting (design `napix-window`, decision 4)."""
    where, params = _filters(kinds, lanes)
    return bool(session.scalar(text(f"SELECT EXISTS (SELECT 1 FROM fetch_queue WHERE {where})"), params))


def has_now(session: Session, kinds: list[FetchKind] | None = None) -> bool:
    """Whether a runnable row waits at a "now" priority (5 or less; design `data-collection-redesign`, decision 24): a
    cheap `EXISTS` on the partial claim index, read by the sleeping worker every 2 s."""
    where, params = _filters(kinds, None, NOW_BULK)
    return bool(session.scalar(text(f"SELECT EXISTS (SELECT 1 FROM fetch_queue WHERE {where})"), params))


def claim(
    session: Session,
    kinds: list[FetchKind] | None = None,
    *,
    lanes: list[FetchLane] | None = None,
    max_priority: int | None = None,
) -> FetchQueueItem | None:
    """The highest-priority runnable row, marked running. `load` rows are skipped while the load is paused (read
    by this query, so a pause bites at the next claim of any worker); `lanes` narrows the lanes (the runner's
    budget bands, decision 4); `max_priority` takes only rows at that priority or better (the runner's "now" claim,
    design `data-collection-redesign`, decision 24). Returns None when nothing is runnable."""
    where, params = _filters(kinds, lanes, max_priority)
    row = session.execute(
        text(
            f"""
            UPDATE fetch_queue SET status = 'running', started_at = now(), attempts = attempts + 1
            WHERE id = (
                SELECT id FROM fetch_queue
                WHERE {where}
                ORDER BY priority, created_at, id
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING id
            """
        ),
        params,
    ).first()
    if row is None:
        return None
    return session.get(FetchQueueItem, row[0], populate_existing=True)  # the row as just updated


def failure_kind(kind: FetchKind | str) -> str:
    """The `source_failures.kind` of a queue kind: `fetch_<kind>` (design safety-fixes, decision 10)."""
    return f"fetch_{FetchKind(kind).value}"


def request_tags(session: Session, item_id: uuid.UUID, *, lock: bool = False) -> list[str]:
    """The requests the row's run is for (`result.request_ids`), read as stored now; `lock` takes the row lock, so no
    `enqueue` changes them before the transaction ends."""
    tags = session.scalar(
        text(
            "SELECT result -> 'request_ids' FROM fetch_queue WHERE id = :id" + (" FOR UPDATE" if lock else "")
        ),
        {"id": item_id},
    )
    return [str(t) for t in tags] if isinstance(tags, list) else []


def from_parent(session: Session, origin: QueueOrigin) -> QueueOrigin:
    """The origin of what a claimed row spawns, read from the row as it is now (row 174 review): its current priority
    (a bulk request stopped while the row ran spawns at the normal turn, not at its "now" priority) and its requests.
    A row carrying requests spawns in the request lane, whatever lane it was claimed in. The row is locked until the
    transaction ends, so Stop waits for the spawned rows and then reaches them."""
    if origin.parent_id is None:
        return origin
    row = session.execute(
        text("SELECT priority, result -> 'request_ids' FROM fetch_queue WHERE id = :id FOR UPDATE"),
        {"id": origin.parent_id},
    ).first()
    if row is None:
        return origin
    tags = tuple(str(t) for t in row[1]) if isinstance(row[1], list) else ()
    out = replace(origin, now_priority=now_priority_of(int(row[0])), request_ids=tags)
    if tags and out.lane != FetchLane.REQUEST:
        # a request took over a row already running in another lane: what it spawns is the request's, in its lane
        # (Stop and the bands treat it as the request's; never a "now" priority in the daily or load lane)
        out = replace(out, lane=FetchLane.REQUEST, settings=None)
    return out


def complete(
    session: Session, item: FetchQueueItem, result: dict[str, Any] | None = None, *, skipped: bool = False
) -> None:
    """`done` (or `skipped`); the row's requests are kept next to the result; an open `fetch_<kind>` failure of the
    same ref is resolved."""
    tags = request_tags(session, item.id, lock=True)
    if tags:
        result = {**(result or {}), "request_ids": tags}
    item.status = FetchStatus.SKIPPED if skipped else FetchStatus.DONE
    item.finished_at = datetime.now(UTC)
    item.result = result
    item.last_error = None
    session.flush()
    source_failures.resolve(session, failure_kind(item.kind), item.ref)


def retry_delay(attempts: int) -> timedelta | None:
    """The wait after the `attempts`-th failed attempt, or None when the row is to be `failed`."""
    if attempts >= MAX_ATTEMPTS:
        return None
    return RETRY_LADDER[max(1, attempts) - 1]


def fail(session: Session, item: FetchQueueItem, error: str, *, family: str | None = None) -> None:
    """Back to pending on the ladder while attempts remain; `failed` after MAX_ATTEMPTS, mirrored into
    `source_failures` (`family` = the exception's class name)."""
    item.last_error = error[:2000]
    item.finished_at = datetime.now(UTC)
    delay = retry_delay(item.attempts)
    if delay is None:
        item.status = FetchStatus.FAILED
        session.flush()
        source_failures.record(session, failure_kind(item.kind), item.ref, error, family)
    else:
        item.status = FetchStatus.PENDING
        item.not_before = datetime.now(UTC) + delay
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
