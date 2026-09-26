"""SourceTrace ingestion and period next dates (plan §3.2, Phase 2), against the `KnowledgeService` interface.

What may be sent: court orders (court records) and uploaded court filings, with CNR, case number, court and
document date. What is never sent: notes, note attachments and internal documents (ground rule 8). Failed
ingestions are retried automatically (up to MAX_ATTEMPTS); persistent failures are recorded in source_failures
for the administration screen. Nothing runs until SOURCETRACE_ENABLED is true and a real connector exists."""

from __future__ import annotations

import asyncio
from datetime import date

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session

from aslms.core.config import get_settings
from aslms.core.errors import IntegrationError
from aslms.domain.alerts import NextDate, NextDateSource
from aslms.domain.cases import Case
from aslms.domain.documents import DocGroup, Document, DocumentKind, Order, SourceTraceStatus, VirusScanStatus
from aslms.domain.events import EventType
from aslms.domain.ops import FailureKind
from aslms.domain.reference import Court
from aslms.domain.sourcetrace import SourceTraceIngestion
from aslms.domain.workflow import CaseNoteAttachment
from aslms.services import cases as case_svc
from aslms.services import events, ops, storage

MAX_ATTEMPTS = 5


def eligible_clause():
    """Court orders and court filings only; never internal documents or note attachments; filings must have
    passed (or skipped, for court records) the virus scan."""
    in_note = select(CaseNoteAttachment.document_id)
    return and_(
        Document.case_id.isnot(None),
        or_(
            and_(Document.doc_group == DocGroup.COURT_RECORD, Document.kind == DocumentKind.COURT_ORDER),
            and_(
                Document.doc_group == DocGroup.COURT_FILING,
                Document.virus_scan_status == VirusScanStatus.CLEAN,
            ),
        ),
        Document.id.notin_(in_note),
    )


def mark_candidates(session: Session) -> int:
    """Queues eligible documents (not_applicable → pending). Runs only when SourceTrace is enabled."""
    if not get_settings().sourcetrace_enabled:
        return 0
    res = session.execute(
        update(Document)
        .where(eligible_clause(), Document.sourcetrace_status == SourceTraceStatus.NOT_APPLICABLE)
        .values(sourcetrace_status=SourceTraceStatus.PENDING)
    )
    return res.rowcount or 0


def _metadata(session: Session, doc: Document) -> dict:
    case = session.get(Case, doc.case_id)
    court = session.get(Court, case.court_id) if case else None
    return {
        "document_id": str(doc.id),
        "cnr": case.cnr if case else None,
        "case_number": case.case_no_text if case else None,
        "court": court.name if court else None,
        "document_date": doc.doc_date.isoformat() if doc.doc_date else None,
        "document_type": doc.doc_type.value,
        "group": doc.doc_group.value,
    }


def ingest_pending(session: Session, ks, limit: int = 100) -> dict[str, int]:
    counts = {"ingested": 0, "failed": 0, "gave_up": 0}
    docs = session.scalars(
        select(Document)
        .where(
            eligible_clause(),
            Document.sourcetrace_status.in_([SourceTraceStatus.PENDING, SourceTraceStatus.FAILED]),
        )
        .order_by(Document.doc_date.desc().nulls_last())
        .limit(limit)
    ).all()
    for doc in docs:
        attempts = (
            session.scalar(
                select(func.count())
                .select_from(SourceTraceIngestion)
                .where(SourceTraceIngestion.document_id == doc.id)
            )
            or 0
        )
        if attempts >= MAX_ATTEMPTS:
            counts["gave_up"] += 1
            continue
        meta = _metadata(session, doc)
        try:
            ref = asyncio.run(
                ks.ingest(
                    document_id=str(doc.id),
                    content=storage.read_blob(doc.storage_key),
                    mime=doc.mime,
                    metadata=meta,
                )
            )
        except (IntegrationError, OSError) as e:
            session.add(
                SourceTraceIngestion(
                    document_id=doc.id,
                    attempt=attempts + 1,
                    ok=False,
                    error=str(e)[:2000],
                    metadata_sent=meta,
                )
            )
            doc.sourcetrace_status = SourceTraceStatus.FAILED
            if attempts + 1 >= MAX_ATTEMPTS:
                ops.record_failure(session, FailureKind.SOURCETRACE, f"ingest:{doc.id}", str(e))
            counts["failed"] += 1
            continue
        session.add(
            SourceTraceIngestion(
                document_id=doc.id, attempt=attempts + 1, ok=True, reference=ref, metadata_sent=meta
            )
        )
        doc.sourcetrace_status, doc.sourcetrace_ref = SourceTraceStatus.INGESTED, ref
        ops.resolve_failure(session, FailureKind.SOURCETRACE, f"ingest:{doc.id}")
        events.emit(
            session,
            EventType.DOCUMENT_INGESTED,
            f"ingested:{doc.id}",
            case_id=doc.case_id,
            payload={"document_id": str(doc.id), "reference": ref},
        )
        counts["ingested"] += 1
    return counts


def read_period_next_dates(session: Session, ks, limit: int = 100) -> dict[str, int]:
    """For latest orders whose next date was flagged (a period or an unclear direction), ask SourceTrace to read
    the order. The answer is advisory (ground rule 8): it becomes an `order_period` next date that still needs a
    person's confirmation."""
    counts = {"read": 0, "no_answer": 0, "failed": 0}
    rows = session.execute(
        select(NextDate, Order, Document)
        .join(Order, Order.id == NextDate.order_id)
        .join(Document, Document.id == Order.document_id)
        .where(
            NextDate.needs_review.is_(True),
            NextDate.source == NextDateSource.MANUAL,
            Document.sourcetrace_status == SourceTraceStatus.INGESTED,
        )
        .limit(limit)
    ).all()
    for nd, order, doc in rows:
        try:
            ans = asyncio.run(ks.next_date(sourcetrace_ref=doc.sourcetrace_ref, order_date=order.order_date))
        except IntegrationError:
            counts["failed"] += 1
            continue
        d = ans.get("next_date")
        if not d:
            counts["no_answer"] += 1
            continue
        case = session.get(Case, nd.case_id)
        case_svc.record_next_date(
            session,
            case,
            date.fromisoformat(str(d)),
            NextDateSource.ORDER_PERIOD,
            order_id=order.id,
            confidence=float(ans.get("confidence") or 0.7),
            needs_review=True,
            note=f"read by SourceTrace: {ans.get('evidence') or ''}"[:1000],
        )
        counts["read"] += 1
    return counts
