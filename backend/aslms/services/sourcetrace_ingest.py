"""Ingestion of court records and court filings into SourceTrace (design `sourcetrace-connector`).

The queue is `documents.sourcetrace_status = 'pending'` with `sourcetrace_next_at` (decision 5): the job claims one
due document at a time with `FOR UPDATE OF documents SKIP LOCKED`, sends it through the connector, writes the
append-only `sourcetrace_ingestions` row and the document's columns, and commits, so two runs never send the same
document and a crash loses at most one attempt. Uploads go before orders, then `doc_date` newest first.

Only court orders and court filings are ever sent, decided by the document's own nature and checked three times
(decision 3): by the claim query, by `assert_sendable` under the row lock just before the bytes leave, and by the
database CHECKs. Never sent: cause lists, note attachments, admin documents, internal uploads, any note text, the
uploader's description and original file name (decision 4). System sends write no `audit_log` row (decision 12);
the human retries do. This is the only service that imports the SourceTrace connector (until row 14)."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, aliased, sessionmaker

from aslms.core.clock import today_ist
from aslms.core.config import Settings
from aslms.domain.cases import Case
from aslms.domain.courts import Court
from aslms.domain.documents import (
    DocGroup,
    DocKind,
    Document,
    Order,
    ScanStatus,
    SourcetraceStatus,
    Visibility,
)
from aslms.domain.ops import JobRun, JobStatus, SourceFailure
from aslms.domain.org import User
from aslms.domain.reference import RefDocType
from aslms.domain.workflow import SourcetraceIngestion
from aslms.integration.sourcetrace import (
    IngestItem,
    SourceTraceConnector,
    SourceTraceRejected,
    SourceTraceUnavailable,
    connector_state,
)
from aslms.services.audit import Actor, write_audit
from aslms.services.storage import EXT_FOR_MIME, LocalStore
from aslms.services.visibility import document_visible_condition, require_visible_document

log = logging.getLogger(__name__)

JOB = "sourcetrace_ingest"
FAILURE_KIND = "sourcetrace_ingestion"
GUARD_KIND = "sourcetrace_guard"
MAX_REFERENCE = 200
MAX_ERROR = 2000
BACKOFF_BASE = timedelta(minutes=10)
RETRY_FAMILIES = frozenset({"unavailable", "timeout", "error"})
STOP_FAMILIES = frozenset({"unavailable", "timeout"})  # SourceTrace is down: the next run tries again


class NotSendable(ValueError):
    """The document must not leave the portal (decision 3); nothing is sent."""


class NotRetryable(ValueError):
    """Only a `failed` document, or a `pending` one waiting on back-off, can be retried (HTTP 409)."""

    code, http_status = "not_retryable", 409


@dataclass(frozen=True)
class IngestConfig:
    batch: int = 20
    run_seconds: float = 240.0
    timeout_seconds: float = 60.0
    max_attempts: int = 5

    @classmethod
    def from_settings(cls, settings: Settings) -> IngestConfig:
        return cls(
            batch=settings.sourcetrace_batch,
            run_seconds=settings.sourcetrace_run_seconds,
            timeout_seconds=settings.sourcetrace_timeout_seconds,
            max_attempts=settings.sourcetrace_max_attempts,
        )


@dataclass(frozen=True)
class Outcome:
    """`result`: ingested / retrying / failed / guarded; `family` the error family of a failed attempt."""

    result: str
    family: str | None = None
    reference: str | None = None


@dataclass
class _Attempt:
    ok: bool
    reference: str | None = None
    raw: dict[str, Any] | None = None
    error: str | None = None
    family: str | None = None
    duration_ms: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


def _now() -> datetime:
    return datetime.now(UTC)


def _value(v: Any) -> Any:
    return v.value if hasattr(v, "value") else v


# ------------------------------------------------------------------------------------------------ pure rules


def backoff(attempts: int) -> timedelta:
    """Decision 7: 10 minutes × 2^(attempts − 1) — 10, 20, 40, 80 minutes."""
    return BACKOFF_BASE * (2 ** max(0, attempts - 1))


def _source_kind(doc: Document) -> str:
    return "court_order" if DocKind(doc.kind) == DocKind.ORDER else "court_filing"


def _clean_part(s: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in s.strip())


def filename_for(doc: Document, case: Case | None, order: Order | None) -> str:
    """Synthetic names only (decision 4): `<CNR>_<order_no>_<date>.pdf` for orders, `<ref_no with dashes>.<ext>`
    for uploads. The uploader's original file name is never sent."""
    ext = EXT_FOR_MIME.get(doc.mime, "bin")
    if DocKind(doc.kind) == DocKind.ORDER and order is not None:
        cnr = (case.cnr if case is not None else None) or "case"
        return f"{_clean_part(cnr)}_{_clean_part(order.order_no)}_{order.order_date.isoformat()}.{ext}"
    base = (doc.ref_no or str(doc.id)).replace("/", "-")
    return f"{_clean_part(base)}.{ext}"


def build_metadata(
    doc: Document,
    case: Case,
    court: Court | None,
    order: Order | None,
    *,
    doc_type_label: str | None = None,
) -> dict[str, Any]:
    """Decision 4, pure: exactly the court-public fields; stored verbatim in `metadata_sent`."""
    is_order = DocKind(doc.kind) == DocKind.ORDER
    doc_date = order.order_date if is_order and order is not None else doc.doc_date
    meta: dict[str, Any] = {
        "external_id": str(doc.id),
        "source_kind": _source_kind(doc),
        "doc_type": _value(doc.doc_type),
        "doc_type_label": doc_type_label or _value(doc.doc_type),
        "document_date": doc_date.isoformat() if doc_date else None,
        "cnr": case.cnr,
        "case_number": case.case_no_text,
        "court": {"est_code": court.est_code, "name": court.name} if court is not None else None,
        "filename": filename_for(doc, case, order),
        "mime": doc.mime,
        "size_bytes": int(doc.size_bytes),
        "sha256": doc.sha256,
    }
    if is_order and order is not None:
        meta["order_no"] = order.order_no
        meta["order_kind"] = _value(order.kind)
        meta["order_judge_name"] = order.order_judge_name
    return meta


def assert_sendable(doc: Document, case: Case | None, order: Order | None) -> None:
    """Decision 3: (a) an order PDF of the court (`court_record`, scan `skipped`, an `orders` row pointing at it)
    or a clean court filing; (b) not private to the office; (c) not archived; (d) the case has a CNR."""
    kind = DocKind(doc.kind)
    group = DocGroup(doc.doc_group)
    scan = ScanStatus(doc.virus_scan_status)
    if kind == DocKind.ORDER:
        if group != DocGroup.COURT_RECORD or scan != ScanStatus.SKIPPED:
            raise NotSendable("an order document must be a court record fetched by the system")
        if order is None or order.document_id != doc.id:
            raise NotSendable("no order points at this document")
    elif kind == DocKind.UPLOAD:
        if group != DocGroup.COURT_FILING:
            raise NotSendable("only court filings among the uploads are sent")
        if scan != ScanStatus.CLEAN:
            raise NotSendable("the upload has no clean virus scan")
    else:
        raise NotSendable(f"documents of kind {kind.value} are never sent")
    if Visibility(doc.visibility) == Visibility.PRIVATE_TO_OFFICE:
        raise NotSendable("a document private to the office is not sent")
    if doc.archived_at is not None:
        raise NotSendable("an archived document is not sent")
    if case is None or doc.case_id != case.id:
        raise NotSendable("the document has no case")
    if not (case.cnr or "").strip():
        raise NotSendable("the case has no CNR yet")


# ------------------------------------------------------------------------------------------------ the queue


def _has_order():
    return exists(select(Order.id).where(Order.document_id == Document.id))


def nature_condition():
    """Decision 3 (a) and (b) in SQL: the kinds of documents that may ever be sent."""
    return and_(
        or_(
            and_(
                Document.kind == DocKind.ORDER,
                Document.doc_group == DocGroup.COURT_RECORD,
                Document.virus_scan_status == ScanStatus.SKIPPED,
                _has_order(),
            ),
            and_(
                Document.kind == DocKind.UPLOAD,
                Document.doc_group == DocGroup.COURT_FILING,
                Document.virus_scan_status == ScanStatus.CLEAN,
            ),
        ),
        Document.visibility != Visibility.PRIVATE_TO_OFFICE,
    )


def _has_cnr():
    return and_(Case.cnr.is_not(None), Case.cnr != "")


def _due(now: datetime):
    return or_(Document.sourcetrace_next_at.is_(None), Document.sourcetrace_next_at <= now)


def _queue_conditions():
    return (
        Document.sourcetrace_status == SourcetraceStatus.PENDING,
        Document.archived_at.is_(None),
        nature_condition(),
        _has_cnr(),
    )


def claim_due(
    session: Session,
    *,
    document_id: uuid.UUID | None = None,
    exclude: set[uuid.UUID] | None = None,
) -> Document | None:
    """Decisions 3, 5 and 8: the next sendable, due, pending document, locked (`FOR UPDATE OF documents SKIP
    LOCKED`). A filing whose case has no CNR is not claimed. An explicit `document_id` (the CLI) is claimed
    without waiting for its back-off."""
    stmt = select(Document).join(Case, Case.id == Document.case_id).where(*_queue_conditions())
    if document_id is not None:
        stmt = stmt.where(Document.id == document_id)
    else:
        stmt = stmt.where(_due(_now()))
    if exclude:
        stmt = stmt.where(Document.id.not_in(list(exclude)))
    stmt = (
        stmt.order_by(
            (Document.kind == DocKind.UPLOAD).desc(),
            Document.doc_date.desc().nulls_last(),
            Document.created_at,
        )
        .limit(1)
        .with_for_update(of=Document, skip_locked=True)
        .execution_options(populate_existing=True)
    )
    return session.scalar(stmt)


def _order_of(session: Session, doc: Document) -> Order | None:
    """Decision 11: a shared order PDF is sent with the case of `documents.case_id`, so that case's order first."""
    if DocKind(doc.kind) != DocKind.ORDER:
        return None
    stmt = select(Order).where(Order.document_id == doc.id)
    if doc.case_id is not None:
        stmt = stmt.order_by((Order.case_id == doc.case_id).desc(), Order.order_date.desc())
    return session.scalar(stmt.limit(1))


def _record_failure(session: Session, kind: str, ref: str, error: str, family: str | None) -> None:
    stmt = pg_insert(SourceFailure).values(
        kind=kind, ref=ref[:300], error=error[:MAX_ERROR], error_family=family
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["kind", "ref"],
        set_={
            "error": stmt.excluded.error,
            "error_family": stmt.excluded.error_family,
            "last_seen": func.now(),
            "attempts": SourceFailure.attempts + 1,
            "resolved_at": None,
        },
    )
    session.execute(stmt)


def _resolve_failure(session: Session, doc_id: uuid.UUID) -> None:
    session.execute(
        update(SourceFailure)
        .where(
            SourceFailure.kind == FAILURE_KIND,
            SourceFailure.ref == str(doc_id),
            SourceFailure.resolved_at.is_(None),
        )
        .values(resolved_at=func.now())
    )


async def _send(connector: SourceTraceConnector, item: IngestItem, timeout: float) -> _Attempt:
    started = time.monotonic()

    def took() -> int:
        return int((time.monotonic() - started) * 1000)

    try:
        result = await asyncio.wait_for(connector.ingest(item), timeout=timeout)
    except TimeoutError:
        return _Attempt(False, error=f"no answer within {timeout:g} s", family="timeout", duration_ms=took())
    except SourceTraceUnavailable as exc:
        return _Attempt(
            False, error=str(exc) or "unavailable", family="unavailable", raw=exc.response, duration_ms=took()
        )
    except SourceTraceRejected as exc:
        return _Attempt(
            False, error=str(exc) or "rejected", family="rejected", raw=exc.response, duration_ms=took()
        )
    except Exception as exc:  # noqa: BLE001 — any connector failure is a recorded, retried attempt
        return _Attempt(False, error=f"{exc.__class__.__name__}: {exc}", family="error", duration_ms=took())
    reference = getattr(result, "reference", None)
    raw = getattr(result, "raw", None)
    raw = raw if isinstance(raw, dict) else None
    if not isinstance(reference, str) or not reference.strip() or len(reference) > MAX_REFERENCE:
        shown = reference if not isinstance(reference, str) else f"{len(reference)} characters"
        return _Attempt(
            False,
            error=f"malformed reference from SourceTrace ({shown})",
            family="protocol",
            raw=raw,
            duration_ms=took(),
        )
    return _Attempt(True, reference=reference, raw=raw, duration_ms=took())


def _write_attempt(
    session: Session, connector: SourceTraceConnector, doc: Document, attempt: _Attempt, meta: dict[str, Any]
) -> None:
    session.add(
        SourcetraceIngestion(
            document_id=doc.id,
            attempt=doc.sourcetrace_attempts,
            ok=attempt.ok,
            connector=str(getattr(connector, "name", "unknown"))[:40],
            reference=attempt.reference,
            error=None if attempt.ok else (attempt.error or "failed")[:MAX_ERROR],
            error_family=attempt.family if not attempt.ok else None,
            duration_ms=attempt.duration_ms,
            metadata_sent=meta,
            response=attempt.raw,
        )
    )


async def ingest_one(
    session: Session,
    connector: SourceTraceConnector,
    store: LocalStore,
    doc: Document,
    config: IngestConfig,
) -> Outcome:
    """Decisions 3, 4, 7: guard, read the file, send with a timeout, write the attempt and the document's
    columns, write or resolve `source_failures`. `doc` is locked by the caller. Never raises for a send."""
    case = session.get(Case, doc.case_id) if doc.case_id is not None else None
    order = _order_of(session, doc)
    try:
        assert_sendable(doc, case, order)
    except NotSendable as exc:
        _record_failure(session, GUARD_KIND, str(doc.id), str(exc), "guard")
        log.warning("SourceTrace guard refused document %s: %s", doc.id, exc)
        session.flush()
        return Outcome("guarded", "guard")
    court = session.get(Court, case.court_id) if case is not None else None
    label_row = session.get(RefDocType, _value(doc.doc_type))
    meta = build_metadata(doc, case, court, order, doc_type_label=label_row.label if label_row else None)
    try:
        content = store.get(doc.storage_key)
    except OSError as exc:
        attempt = _Attempt(False, error=f"file missing from the store: {exc}", family="store")
    else:
        item = IngestItem(
            document_id=doc.id, content=content, mime=doc.mime, filename=meta["filename"], metadata=meta
        )
        attempt = await _send(connector, item, config.timeout_seconds)
    now = _now()
    doc.sourcetrace_attempts = int(doc.sourcetrace_attempts or 0) + 1
    _write_attempt(session, connector, doc, attempt, meta)
    if attempt.ok:
        doc.sourcetrace_status = SourcetraceStatus.INGESTED
        doc.sourcetrace_ref = attempt.reference
        doc.sourcetrace_ingested_at = now
        doc.sourcetrace_next_at = None
        _resolve_failure(session, doc.id)
        outcome = Outcome("ingested", reference=attempt.reference)
    elif attempt.family in RETRY_FAMILIES and doc.sourcetrace_attempts < config.max_attempts:
        doc.sourcetrace_status = SourcetraceStatus.PENDING
        doc.sourcetrace_next_at = now + backoff(doc.sourcetrace_attempts)
        outcome = Outcome("retrying", attempt.family)
    else:
        doc.sourcetrace_status = SourcetraceStatus.FAILED
        doc.sourcetrace_next_at = None
        _record_failure(session, FAILURE_KIND, str(doc.id), attempt.error or "failed", attempt.family)
        outcome = Outcome("failed", attempt.family)
    session.flush()
    return outcome


def _counters() -> dict[str, Any]:
    return {"claimed": 0, "ingested": 0, "retrying": 0, "failed": 0, "guarded": 0, "stopped": None}


async def ingest_pending(
    Session: sessionmaker,
    connector: SourceTraceConnector,
    store: LocalStore,
    config: IngestConfig,
    *,
    document_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Decisions 5 and 14: one session per document, committed each time; stops on the batch size, the run time,
    or the first unavailable / timeout outcome. `stopped`: unavailable / batch / time / empty."""
    started = time.monotonic()
    counters = _counters()
    seen: set[uuid.UUID] = set()
    while True:
        if counters["claimed"] >= config.batch:
            counters["stopped"] = "batch"
            break
        if time.monotonic() - started >= config.run_seconds:
            counters["stopped"] = "time"
            break
        with Session() as s:
            doc = claim_due(s, document_id=document_id, exclude=seen)
            if doc is None:
                s.rollback()
                counters["stopped"] = "empty"
                break
            seen.add(doc.id)
            counters["claimed"] += 1
            try:
                outcome = await ingest_one(s, connector, store, doc, config)
            except BaseException:
                s.rollback()
                raise
            s.commit()
        counters[outcome.result] += 1
        if outcome.family in STOP_FAMILIES:
            counters["stopped"] = "unavailable"
            break
    return counters


def run(
    Session: sessionmaker,
    connector: SourceTraceConnector,
    store: LocalStore,
    config: IngestConfig,
    *,
    document_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """The sync wrapper for Celery and the CLI: a `job_runs` row (`job = sourcetrace_ingest`), status `partial`
    when anything failed, was retried or was refused by the guard."""
    with Session() as s:
        job = JobRun(job=JOB, run_date=today_ist(_now()))
        s.add(job)
        s.commit()
        job_id = job.id
    try:
        counters = asyncio.run(ingest_pending(Session, connector, store, config, document_id=document_id))
    except Exception as exc:
        with Session() as s:
            row = s.get(JobRun, job_id)
            row.status, row.error = JobStatus.FAILED, f"{exc.__class__.__name__}: {exc}"[:MAX_ERROR]
            row.finished_at = _now()
            s.commit()
        raise
    with Session() as s:
        row = s.get(JobRun, job_id)
        row.counters = counters
        partial = counters["failed"] or counters["retrying"] or counters["guarded"]
        row.status = JobStatus.PARTIAL if partial else JobStatus.SUCCEEDED
        row.finished_at = _now()
        s.commit()
    return counters


# ------------------------------------------------------------------------------------------------ status, lists


def _count(session: Session, *where) -> int:
    return int(session.scalar(select(func.count()).select_from(Document).where(*where)) or 0)


def status(session: Session, settings: Settings) -> dict[str, Any]:
    """State, counts by status for kinds `order` and `upload`, `waiting_cnr`, `due_now`, the oldest pending, and the
    last run. Totals only (no case data)."""
    state = connector_state(settings)
    kinds = Document.kind.in_([DocKind.ORDER, DocKind.UPLOAD])
    rows = session.execute(
        select(Document.sourcetrace_status, func.count()).where(kinds).group_by(Document.sourcetrace_status)
    ).all()
    counts = {s.value: 0 for s in SourcetraceStatus}
    for st, n in rows:
        counts[_value(st)] = int(n)
    pending = Document.sourcetrace_status == SourcetraceStatus.PENDING
    waiting_cnr = int(
        session.scalar(
            select(func.count())
            .select_from(Document)
            .join(Case, Case.id == Document.case_id)
            .where(pending, Document.archived_at.is_(None), nature_condition(), ~_has_cnr())
        )
        or 0
    )
    due_now = int(
        session.scalar(
            select(func.count())
            .select_from(Document)
            .join(Case, Case.id == Document.case_id)
            .where(*_queue_conditions(), _due(_now()))
        )
        or 0
    )
    oldest = session.scalar(select(func.min(Document.created_at)).where(kinds, pending))
    last = session.scalar(select(JobRun).where(JobRun.job == JOB).order_by(JobRun.started_at.desc()).limit(1))
    return {
        "state": state,
        "connector": None,  # a name only once a real connector is configured (`ready`)
        "counts": counts,
        "waiting_cnr": waiting_cnr,
        "due_now": due_now,
        "oldest_pending_at": oldest,
        "last_run": (
            {
                "started_at": last.started_at,
                "finished_at": last.finished_at,
                "status": _value(last.status),
                "counters": last.counters or {},
            }
            if last is not None
            else None
        ),
    }


def failed(
    session: Session, user: User, *, limit: int = 50, offset: int = 0
) -> tuple[list[dict[str, Any]], int]:
    """Failed documents the caller may see (the document visibility rule, in SQL), newest attempt first, each
    with its latest attempt's error, family and time."""
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    last = (
        select(
            SourcetraceIngestion.document_id.label("document_id"),
            func.max(SourcetraceIngestion.created_at).label("at"),
        )
        .group_by(SourcetraceIngestion.document_id)
        .subquery()
    )
    doc_case = aliased(Case)  # the visibility condition correlates on `cases` itself
    base = (
        select(Document, doc_case, last.c.at)
        .join(doc_case, doc_case.id == Document.case_id, isouter=True)
        .join(last, last.c.document_id == Document.id, isouter=True)
        .where(
            Document.sourcetrace_status == SourcetraceStatus.FAILED,
            document_visible_condition(session, user),
        )
    )
    total = int(session.scalar(select(func.count()).select_from(base.order_by(None).subquery())) or 0)
    rows = session.execute(
        base.order_by(last.c.at.desc().nulls_last(), Document.id).limit(limit).offset(offset)
    ).all()
    items = []
    for doc, case, at in rows:
        attempt = session.scalar(
            select(SourcetraceIngestion)
            .where(SourcetraceIngestion.document_id == doc.id)
            .order_by(SourcetraceIngestion.created_at.desc(), SourcetraceIngestion.id.desc())
            .limit(1)
        )
        items.append(
            {
                "document_id": doc.id,
                "ref_no": doc.ref_no,
                "kind": _value(doc.kind),
                "doc_type": _value(doc.doc_type),
                "doc_date": doc.doc_date,
                "case": (
                    {"id": case.id, "ref_no": case.ref_no, "cnr": case.cnr, "case_no_text": case.case_no_text}
                    if case is not None
                    else None
                ),
                "attempts": int(doc.sourcetrace_attempts or 0),
                "last_error": attempt.error if attempt else None,
                "error_family": attempt.error_family if attempt else None,
                "last_attempt_at": attempt.created_at if attempt else at,
            }
        )
    return items, total


# ------------------------------------------------------------------------------------------------ retries


def retry(session: Session, actor: Actor, user: User | None, doc: Document) -> Document:
    """A `failed` document (or a `pending` one waiting on back-off) goes back to `pending` with no attempts and no
    wait; audited `sourcetrace.retry_requested`. `user` (the API) must see the document (`NotVisibleDocument`
    otherwise); the CLI passes `None`."""
    if user is not None:
        require_visible_document(session, user, doc)
    locked = session.scalar(
        select(Document)
        .where(Document.id == doc.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    doc = locked or doc
    st = SourcetraceStatus(doc.sourcetrace_status)
    waiting = st == SourcetraceStatus.PENDING and (
        doc.sourcetrace_next_at is not None or int(doc.sourcetrace_attempts or 0) > 0
    )
    if st != SourcetraceStatus.FAILED and not waiting:
        raise NotRetryable(f"a document that is {st.value} without a failed attempt cannot be retried")
    before = {"sourcetrace_status": st.value, "sourcetrace_attempts": int(doc.sourcetrace_attempts or 0)}
    doc.sourcetrace_status = SourcetraceStatus.PENDING
    doc.sourcetrace_attempts = 0
    doc.sourcetrace_next_at = None
    session.flush()
    write_audit(
        session,
        actor,
        "sourcetrace.retry_requested",
        "document",
        doc.id,
        case_id=doc.case_id,
        before=before,
        after={"sourcetrace_status": SourcetraceStatus.PENDING.value, "sourcetrace_attempts": 0},
    )
    return doc


def retry_all_failed(session: Session, actor: Actor) -> int:
    """Every `failed` document back to `pending` (the CLI); one audit row with the count."""
    ids = list(
        session.scalars(
            select(Document.id)
            .where(Document.sourcetrace_status == SourcetraceStatus.FAILED)
            .with_for_update()
        ).all()
    )
    if ids:
        session.execute(
            update(Document)
            .where(Document.id.in_(ids))
            .values(
                sourcetrace_status=SourcetraceStatus.PENDING, sourcetrace_attempts=0, sourcetrace_next_at=None
            )
        )
    write_audit(
        session,
        actor,
        "sourcetrace.retry_all_failed",
        "document",
        None,
        after={"count": len(ids)},
    )
    session.flush()
    return len(ids)


# ------------------------------------------------------------------------------------------------ the check


def check(session: Session) -> dict[str, int]:
    """`aslms sourcetrace check`: documents that break decision 3 while not `not_applicable` (an archived one only
    while not `ingested`, decision 9; a filing waiting for its CNR is not a breach, decision 8), and ingestion rows
    of documents whose nature is not sendable. Both must be 0."""
    breaking = _count(
        session,
        Document.sourcetrace_status != SourcetraceStatus.NOT_APPLICABLE,
        or_(
            ~nature_condition(),
            and_(
                Document.archived_at.is_not(None),
                Document.sourcetrace_status != SourcetraceStatus.INGESTED,
            ),
        ),
    )
    rows_unsendable = int(
        session.scalar(
            select(func.count())
            .select_from(SourcetraceIngestion)
            .join(Document, Document.id == SourcetraceIngestion.document_id)
            .where(~nature_condition())
        )
        or 0
    )
    return {"documents_breaking_rule": breaking, "ingestions_of_unsendable": rows_unsendable}
