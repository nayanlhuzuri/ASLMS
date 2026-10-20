"""The live data-health view (design `audit-screens`, decisions 5-7): what the daily data cycle, the queue, NAPIX, the
mail outbox, SourceTrace and the source failures look like *now*, for the data-health screen and
`/admin/napix/health`. Reads only, under the report statement timeout; never calls NAPIX. Counts and operational
references (dates, CNRs, order numbers, error texts) only: no party names, note text or document content. The
period report `GET /reports/data-health` stays in `services/reports.py`; both share the daily-cycle helpers of
`reporting_common`. The NAPIX block reads the detected quota window (design `napix-window`, decision 6); who caused
which calls (`by_user`, the call log's user fields) goes only to the NAPIX operators (decision 11)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import String, cast, exists, func, literal, literal_column, or_, select, tuple_
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from aslms.core.config import Settings
from aslms.domain.alerts import Digest, Notification, NotificationStatus
from aslms.domain.courts import MasterSyncRun
from aslms.domain.documents import DocKind, Document, TextStatus
from aslms.domain.ops import (
    FetchKind,
    FetchLane,
    FetchQueueItem,
    FetchStatus,
    JobRun,
    NapixCallLog,
    SourceFailure,
)
from aslms.domain.org import Channel, User
from aslms.domain.reference import Permission
from aslms.integration.napix.hc import API
from aslms.services import access, napix_window, sourcetrace_ingest
from aslms.services.access import Member
from aslms.services.audit_search import AuditInputError, decode_cursor, encode_cursor, like_escape, to_ist
from aslms.services.filetypes import DOC_MIME, JPEG_MIME, PDF_MIME, PNG_MIME
from aslms.services.queue import STALE_RUNNING
from aslms.services.reporting_common import (
    IST_ZONE,
    causelist_counts,
    causelist_day_rows,
    today_ist,
    with_timeout,
)
from aslms.services.visibility import document_visible_condition

DOCUMENT_FAILURE_KINDS = frozenset(
    {"text_extraction", "document_missing", "sourcetrace_ingestion", "sourcetrace_guard"}
)
OVERVIEW_API = API["overview"]  # the call log stores the API path (`overview/overview`)
JOBS_WINDOW = timedelta(days=30)
MAX_LIMIT = 200


def _value(v: Any) -> Any:
    return v.value if hasattr(v, "value") else v


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


def _day_start(d: date) -> datetime:
    return datetime.combine(d, time.min, IST_ZONE).astimezone(UTC)


def _limit(limit: int) -> int:
    return max(1, min(int(limit), MAX_LIMIT))


# ------------------------------------------------------------------------------------------------ NAPIX block


def is_operator(session: Session, user: User | Member | None) -> bool:
    """A NAPIX operator (`admin.napix_refetch` or `admin.masters_sync`) sees who caused each call (design
    `napix-window`, decision 11); False for the CLI without a super admin."""
    if user is None:
        return False
    return access.has(session, user, Permission.ADMIN_NAPIX_REFETCH) or access.has(
        session, user, Permission.ADMIN_MASTERS_SYNC
    )


def window_block(
    session: Session, settings: Settings, now: datetime, window: napix_window.WindowState
) -> dict[str, Any]:
    """`NapixWindowOut`: the detected window, its calls and failures since the observed reset (none while the reset
    is due), and the thresholds."""
    counts = napix_window.calls_since(session, window.observed_at)
    return {
        **window.as_dict(now),
        "calls": counts["calls"],
        "failed": counts["failed"],
        "reserve": settings.napix_rate_reserve,
        "live_reserve": settings.napix_live_reserve,
        "search_floor": settings.napix_search_floor,
    }


def napix_health(
    session: Session, settings: Settings, now: datetime | None = None, *, operator: bool = False
) -> dict[str, Any]:
    """Decision 5's NAPIX block: the switch as this process sees it, the detected quota window (design
    `napix-window`), today (IST), the last call, the last success, the last failure and the last connectivity check
    (an Overview call outside a runner pass: probes are not checks). `by_user` (the window's and today's top 10 by
    calls) only for an operator, else None. Never a credential."""
    now = _now(now)
    day_start = _day_start(today_ist(now))
    state = napix_window.current(session, settings, now)
    t_calls, t_failed, t_unverified = session.execute(
        select(
            func.count(),
            func.count().filter(NapixCallLog.ok.is_(False)),
            func.count().filter(NapixCallLog.token_verified.is_(False)),
        ).where(NapixCallLog.called_at >= day_start)
    ).one()
    family = func.coalesce(NapixCallLog.error_family, literal_column("'unknown'"))
    by_family = {
        fam: int(n)
        for fam, n in session.execute(
            select(family, func.count())
            .where(NapixCallLog.called_at >= day_start, NapixCallLog.ok.is_(False))
            .group_by(family)
            .order_by(func.count().desc(), family)
        ).all()
    }
    last_call_at = session.scalar(select(func.max(NapixCallLog.called_at)))
    last_ok_at = session.scalar(select(func.max(NapixCallLog.called_at)).where(NapixCallLog.ok.is_(True)))
    fail = session.scalar(
        select(NapixCallLog)
        .where(NapixCallLog.ok.is_(False))
        .order_by(NapixCallLog.called_at.desc(), NapixCallLog.id.desc())
        .limit(1)
    )
    check = session.scalar(
        select(NapixCallLog)
        .where(NapixCallLog.api == OVERVIEW_API, NapixCallLog.job_run_id.is_(None))
        .order_by(NapixCallLog.called_at.desc(), NapixCallLog.id.desc())
        .limit(1)
    )
    return {
        "enabled": bool(settings.napix_configured),
        "est_code": settings.napix_est_code,
        "window": window_block(session, settings, now, state),
        "today": {
            "calls": int(t_calls),
            "failed": int(t_failed),
            "by_family": by_family,
            "token_unverified": int(t_unverified),
        },
        "last_call_at": to_ist(last_call_at),
        "last_ok_at": to_ist(last_ok_at),
        "last_failure": (
            {
                "called_at": to_ist(fail.called_at),
                "api": fail.api,
                "http_status": fail.http_status,
                "napix_status": fail.napix_status,
                "error_family": fail.error_family,
            }
            if fail is not None
            else None
        ),
        "last_check": (
            {
                "called_at": to_ist(check.called_at),
                "ok": check.ok,
                "duration_ms": check.duration_ms,
                "token_verified": check.token_verified,
                "error_family": check.error_family,
            }
            if check is not None
            else None
        ),
        "by_user": (
            {
                "window": napix_window.by_user(session, state.observed_at),
                "today": napix_window.by_user(session, day_start),
            }
            if operator
            else None
        ),
    }


# ------------------------------------------------------------------------------------------------ the screen


def queue_depths(session: Session, now: datetime | None = None) -> dict[str, Any]:
    """Rows per kind and state: `pending` split into runnable and waiting on `not_before`, `running` with the
    stale ones (older than `STALE_RUNNING`), `failed`, `skipped`, `done`; the pending rows of each kind split by
    lane (design `data-load-console`); the oldest runnable row."""
    now = _now(now)
    q = FetchQueueItem
    pending = q.status == FetchStatus.PENDING
    runnable = pending & or_(q.not_before.is_(None), q.not_before <= now)
    running = q.status == FetchStatus.RUNNING
    rows = {
        _value(kind): r
        for kind, *r in session.execute(
            select(
                q.kind,
                func.count().filter(pending),
                func.count().filter(runnable),
                func.count().filter(running),
                func.count().filter(running & (q.started_at < now - STALE_RUNNING)),
                func.count().filter(q.status == FetchStatus.FAILED),
                func.count().filter(q.status == FetchStatus.SKIPPED),
                func.count().filter(q.status == FetchStatus.DONE),
            ).group_by(q.kind)
        ).all()
    }
    lanes: dict[str, dict[str, int]] = {}
    for kind, lane, n in session.execute(
        select(q.kind, q.lane, func.count()).where(pending).group_by(q.kind, q.lane)
    ).all():
        lanes.setdefault(_value(kind), {})[_value(lane)] = int(n)
    by_kind = []
    for kind in FetchKind:
        p, r, run, stale, failed, skipped, done = rows.get(kind.value, (0,) * 7)
        by_lane = {lane.value: lanes.get(kind.value, {}).get(lane.value, 0) for lane in FetchLane}
        by_kind.append(
            {
                "kind": kind.value,
                "pending": int(p),
                "runnable": int(r),
                "waiting": int(p) - int(r),
                "running": int(run),
                "stale": int(stale),
                "failed": int(failed),
                "skipped": int(skipped),
                "done": int(done),
                "by_lane": by_lane,
            }
        )
    oldest = session.scalar(select(func.min(q.created_at)).where(runnable))
    return {
        "by_kind": by_kind,
        "oldest_runnable_at": to_ist(oldest),
        "failed_total": sum(k["failed"] for k in by_kind),
    }


def daily_cycle(session: Session, now: datetime | None = None) -> list[dict[str, Any]]:
    """Yesterday, today and tomorrow (IST): the `causelist_day` row and the lists stored and parsed."""
    today = today_ist(_now(now))
    days = [
        (today - timedelta(days=1), "yesterday"),
        (today, "today"),
        (today + timedelta(days=1), "tomorrow"),
    ]
    queue_rows = causelist_day_rows(session, [d for d, _ in days])
    counts = causelist_counts(session, days[0][0], days[-1][0])
    out = []
    for d, label in days:
        row = queue_rows.get(d)
        c = counts.get(d, {"lists_stored": 0, "entries_parsed": 0, "lists_parse_failed": 0})
        out.append(
            {
                "date": d,
                "label": label,
                "causelist_day": (
                    {
                        "status": row["status"],
                        "attempts": row["attempts"],
                        "finished_at": to_ist(row["finished_at"]),
                        "last_error": row["last_error"],
                    }
                    if row is not None
                    else None
                ),
                **c,
            }
        )
    return out


def status_batches(session: Session) -> dict[str, Any] | None:
    """The latest date with Current Status batches and its done / failed / pending / running counts."""
    q = FetchQueueItem
    day = func.split_part(q.ref, ":", 1)
    latest = session.scalar(select(func.max(day)).where(q.kind == FetchKind.STATUS_BATCH))
    if latest is None:
        return None
    done, failed, pending, running = session.execute(
        select(
            func.count().filter(q.status == FetchStatus.DONE),
            func.count().filter(q.status == FetchStatus.FAILED),
            func.count().filter(q.status == FetchStatus.PENDING),
            func.count().filter(q.status == FetchStatus.RUNNING),
        ).where(q.kind == FetchKind.STATUS_BATCH, day == latest)
    ).one()
    try:
        latest_date: date | str = date.fromisoformat(latest)
    except ValueError:
        latest_date = latest
    return {
        "date": latest_date,
        "done": int(done),
        "failed": int(failed),
        "pending": int(pending),
        "running": int(running),
    }


def masters(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(
        select(MasterSyncRun.master, MasterSyncRun.fetched_at, MasterSyncRun.row_count)
        .ext(distinct_on(MasterSyncRun.master))
        .order_by(MasterSyncRun.master, MasterSyncRun.fetched_at.desc())
    ).all()
    return [{"master": _value(m), "fetched_at": to_ist(at), "row_count": int(n)} for m, at, n in rows]


def jobs(session: Session, now: datetime | None = None) -> list[dict[str, Any]]:
    """The latest run of each job seen in the last 30 days."""
    since = _now(now) - JOBS_WINDOW
    rows = session.scalars(
        select(JobRun)
        .where(JobRun.started_at >= since)
        .ext(distinct_on(JobRun.job))
        .order_by(JobRun.job, JobRun.started_at.desc())
    ).all()
    return [
        {
            "job": r.job,
            "started_at": to_ist(r.started_at),
            "finished_at": to_ist(r.finished_at),
            "status": _value(r.status),
            "counters": r.counters or {},
        }
        for r in rows
    ]


def mail(session: Session) -> dict[str, Any]:
    """The e-mail outbox (alerts-notifications decision 17): notifications and digests queued and failed."""
    email = Notification.channel == Channel.EMAIL
    queued, failed, oldest = session.execute(
        select(
            func.count().filter(Notification.status == NotificationStatus.QUEUED),
            func.count().filter(Notification.status == NotificationStatus.FAILED),
            func.min(Notification.created_at).filter(Notification.status == NotificationStatus.QUEUED),
        ).where(email)
    ).one()
    d_queued, d_failed = session.execute(
        select(
            func.count().filter(Digest.status == NotificationStatus.QUEUED),
            func.count().filter(Digest.status == NotificationStatus.FAILED),
        )
    ).one()
    return {
        "email_queued": int(queued),
        "email_failed": int(failed),
        "email_oldest_queued_at": to_ist(oldest),
        "digests_queued": int(d_queued),
        "digests_failed": int(d_failed),
    }


def failures(session: Session) -> list[dict[str, Any]]:
    """Open source failures by kind (counts only)."""
    return [
        {"kind": kind, "open": int(n), "oldest_first_seen": to_ist(oldest)}
        for kind, n, oldest in session.execute(
            select(SourceFailure.kind, func.count(), func.min(SourceFailure.first_seen))
            .where(SourceFailure.resolved_at.is_(None))
            .group_by(SourceFailure.kind)
            .order_by(SourceFailure.kind)
        ).all()
    ]


TEXT_KINDS = (DocKind.ORDER, DocKind.UPLOAD, DocKind.ATTACHMENT)


def _none_bucket(mime: str) -> str:
    if mime == PDF_MIME:
        return "scanned_pdf"
    if mime in (JPEG_MIME, PNG_MIME):
        return "image"
    if mime == DOC_MIME:
        return "doc"
    return "other"


def documents_text(session: Session) -> dict[str, Any]:
    """Design `document-ocr`, decision 4: documents by kind (`order`, `upload`, `attachment`; never `causelist` or
    `admin`) and text status, `none` split by type into scanned PDFs, images and old Word files (`other`: a Word
    file with no text in it). One grouped count; totals only, no case data."""
    out: dict[str, Any] = {
        kind.value: {
            "pending": 0,
            "extracted": 0,
            "failed": 0,
            "none": {"scanned_pdf": 0, "image": 0, "doc": 0, "other": 0},
        }
        for kind in TEXT_KINDS
    }
    rows = session.execute(
        select(Document.kind, Document.text_status, Document.mime, func.count())
        .where(Document.kind.in_(TEXT_KINDS))
        .group_by(Document.kind, Document.text_status, Document.mime)
    ).all()
    for kind, status, mime, n in rows:
        block = out[_value(kind)]
        if _value(status) == TextStatus.NONE.value:
            block["none"][_none_bucket(mime)] += int(n)
        else:
            block[_value(status)] += int(n)
    return out


def snapshot(
    session: Session, user: User | Member | None, settings: Settings, now: datetime | None = None
) -> dict[str, Any]:
    """Decision 5: the whole screen in one transaction (one consistent snapshot). Counts only; one block depends on
    the caller: the NAPIX block's `by_user` is filled for the NAPIX operators only (design `napix-window`, decision
    11). `user` is `None` for the CLI before a super admin exists (no operator then). `documents_text` counts
    documents by text status (design `document-ocr`, decision 4)."""
    now = _now(now)
    with_timeout(session, settings.report_statement_timeout_seconds)
    return {
        "as_of": to_ist(now),
        "napix": napix_health(session, settings, now, operator=is_operator(session, user)),
        "queue": queue_depths(session, now),
        "daily_cycle": daily_cycle(session, now),
        "status_batches": status_batches(session),
        "masters": masters(session),
        "jobs": jobs(session, now),
        "mail": mail(session),
        "sourcetrace": sourcetrace_ingest.status(session, settings),
        "failures": failures(session),
        "documents_text": documents_text(session),
    }


# ------------------------------------------------------------------------------------------------ detail lists


def queue_rows(
    session: Session,
    *,
    kind: FetchKind | None = None,
    status: FetchStatus | None = None,
    ref_prefix: str | None = None,
    limit: int = 50,
    offset: int = 0,
    lane: FetchLane | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Queue rows by kind, status, lane and ref prefix, highest priority and oldest first, with `total`."""
    q = FetchQueueItem
    conds = []
    if lane is not None:
        conds.append(q.lane == lane)
    if kind is not None:
        conds.append(q.kind == kind)
    if status is not None:
        conds.append(q.status == status)
    if ref_prefix:
        conds.append(q.ref.like(like_escape(ref_prefix) + "%", escape="\\"))
    total = int(session.scalar(select(func.count()).select_from(q).where(*conds)) or 0)
    rows = session.scalars(
        select(q)
        .where(*conds)
        .order_by(q.priority, q.created_at, q.id)
        .limit(_limit(limit))
        .offset(max(0, int(offset)))
    ).all()
    items = [
        {
            "id": r.id,
            "kind": _value(r.kind),
            "ref": r.ref,
            "priority": r.priority,
            "status": _value(r.status),
            "attempts": r.attempts,
            "not_before": to_ist(r.not_before),
            "started_at": to_ist(r.started_at),
            "finished_at": to_ist(r.finished_at),
            "last_error": r.last_error,
            "result": r.result,
            "updated_at": to_ist(r.updated_at),
            "lane": _value(r.lane),
            "list_date": r.list_date,
        }
        for r in rows
    ]
    return items, total


CALL_COLUMNS = (
    NapixCallLog.id,
    NapixCallLog.called_at,
    NapixCallLog.api,
    NapixCallLog.http_status,
    NapixCallLog.napix_status,
    NapixCallLog.ok,
    NapixCallLog.error_family,
    NapixCallLog.error,
    NapixCallLog.duration_ms,
    NapixCallLog.token_verified,
    NapixCallLog.rate_limit_remaining,
    NapixCallLog.job_run_id,
    NapixCallLog.lane,
)


def call_rows(
    session: Session,
    *,
    from_: date | None = None,
    to: date | None = None,
    api: str | None = None,
    ok: bool | None = None,
    cursor: str | None = None,
    limit: int = 50,
    now: datetime | None = None,
    user_id: uuid.UUID | None = None,
    operator: bool = False,
) -> tuple[list[dict[str, Any]], str | None]:
    """Call log rows of an IST period (default today), newest first, keyset like the audit search. Selects the
    columns by name: never `params` (the call log has only `params_sha256`, which is not shown either). Each row has
    its lane; the user who caused it (`user_id`, `user_name`) and the `user_id` filter only for an operator (design
    `napix-window`, decision 11): a non-operator's filter is `Forbidden`."""
    if user_id is not None and not operator:
        raise access.Forbidden("admin.napix_refetch or admin.masters_sync is needed to filter calls by user")
    today = today_ist(_now(now))
    from_ = from_ or (to if to is not None and to < today else today)
    to = to or today
    if from_ > to:
        raise AuditInputError("bad_period", "from must not be after to")
    conds = [
        NapixCallLog.called_at >= _day_start(from_),
        NapixCallLog.called_at < _day_start(to + timedelta(days=1)),
    ]
    if api:
        conds.append(NapixCallLog.api == API.get(api, api))
    if ok is not None:
        conds.append(NapixCallLog.ok.is_(ok))
    if user_id is not None:
        conds.append(NapixCallLog.user_id == user_id)
    if cursor:
        at, row_id = decode_cursor(cursor)
        conds.append(tuple_(NapixCallLog.called_at, NapixCallLog.id) < tuple_(at, row_id))
    n = _limit(limit)
    stmt = select(*CALL_COLUMNS)
    if operator:
        stmt = select(*CALL_COLUMNS, NapixCallLog.user_id, User.full_name.label("user_name")).outerjoin(
            User, User.id == NapixCallLog.user_id
        )
    rows = session.execute(
        stmt.where(*conds).order_by(NapixCallLog.called_at.desc(), NapixCallLog.id.desc()).limit(n + 1)
    ).all()
    more = len(rows) > n
    rows = rows[:n]
    items = [
        {
            "id": r.id,
            "called_at": to_ist(r.called_at),
            "api": r.api,
            "http_status": r.http_status,
            "napix_status": r.napix_status,
            "ok": r.ok,
            "error_family": r.error_family,
            "error": r.error,
            "duration_ms": r.duration_ms,
            "token_verified": r.token_verified,
            "rate_limit_remaining": r.rate_limit_remaining,
            "job_run_id": r.job_run_id,
            "lane": _value(r.lane),
            "user_id": r.user_id if operator else None,
            "user_name": r.user_name if operator else None,
        }
        for r in rows
    ]
    return items, (encode_cursor(rows[-1].called_at, rows[-1].id) if more and rows else None)


def failure_condition(session: Session, user: User | Member):
    """Decision 7: rows whose `ref` is a document id are shown only when the document is visible to the caller by
    the document rule; rows of documents without a case (and refs that are no document) only to the super admin."""
    if any(m.is_super_admin for m in access.members(session, user)):
        return literal(True)
    visible_doc = exists(
        select(literal(1))
        .select_from(Document)
        .where(cast(Document.id, String) == SourceFailure.ref, document_visible_condition(session, user))
    )
    return or_(SourceFailure.kind.not_in(list(DOCUMENT_FAILURE_KINDS)), visible_doc)


def failure_rows(
    session: Session,
    user: User | Member,
    *,
    kind: str | None = None,
    open_only: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    conds = [failure_condition(session, user)]
    if kind:
        conds.append(SourceFailure.kind == kind)
    if open_only:
        conds.append(SourceFailure.resolved_at.is_(None))
    total = int(session.scalar(select(func.count()).select_from(SourceFailure).where(*conds)) or 0)
    rows = session.scalars(
        select(SourceFailure)
        .where(*conds)
        .order_by(SourceFailure.last_seen.desc(), SourceFailure.id.desc())
        .limit(_limit(limit))
        .offset(max(0, int(offset)))
    ).all()
    items = [
        {
            "id": r.id,
            "kind": r.kind,
            "ref": r.ref,
            "error": r.error,
            "error_family": r.error_family,
            "first_seen": to_ist(r.first_seen),
            "last_seen": to_ist(r.last_seen),
            "attempts": r.attempts,
            "resolved_at": to_ist(r.resolved_at),
        }
        for r in rows
    ]
    return items, total
