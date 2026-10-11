"""Pipeline stage 5: order PDFs. Every order reference the dossier gives (`orders` rows) gets a low-priority
`order_pdf` queue row (`<CNR>|<order_no>|<YYYY-MM-DD>`); Show Order → `documents` → `orders.document_id`.
A 628 means the court has not published the PDF: recorded as `not_available` and retried by the weekly
sweep, never forever."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aslms.core.errors import NapixNotFound
from aslms.domain.cases import Case, CaseStatus
from aslms.domain.documents import (
    DocGroup,
    DocKind,
    Document,
    DownloadStatus,
    Order,
    OrderKind,
    ScanStatus,
    SourcetraceStatus,
    TextStatus,
    Visibility,
)
from aslms.domain.ops import FetchKind
from aslms.domain.reference import DocType, EventType
from aslms.integration.napix.hc import NapixHighCourt
from aslms.services import queue
from aslms.services.cases import emit_event
from aslms.services.load_policy import DAILY, QueueOrigin
from aslms.services.storage import LocalStore


def order_ref(cnr: str, order: Order) -> str:
    return f"{cnr}|{order.order_no}|{order.order_date.isoformat()}"


def enqueue_order_pdfs(session: Session, case: Case, origin: QueueOrigin | None = None) -> int:
    """Queue the PDFs this case still lacks, in the lane of the work that found them (design `data-load-console`,
    decisions 1 and 5): the daily cycle puts a pending case's PDFs at 40 and a disposed case's at 80; the load uses
    its policy; a person's request 40."""
    if not case.cnr:
        return 0
    origin = origin or DAILY
    priority = origin.order_pdf_priority(case.status == CaseStatus.PENDING)
    n = 0
    for o in session.scalars(
        select(Order).where(
            Order.case_id == case.id,
            Order.document_id.is_(None),
            Order.download_status == DownloadStatus.PENDING,
        )
    ).all():
        emit_event(
            session,
            EventType.ORDER_FOUND,
            case,
            {"cnr": case.cnr, "order_no": o.order_no, "order_date": o.order_date, "kind": o.kind.value},
            dedupe=f"order_found:{case.cnr}:{o.order_no}:{o.order_date}",
        )
        if queue.enqueue(
            session,
            FetchKind.ORDER_PDF,
            order_ref(case.cnr, o),
            priority,
            lane=origin.lane,
            list_date=origin.list_date,
        ):
            n += 1
    return n


async def fetch_order_pdf(
    session: Session, hc: NapixHighCourt, store: LocalStore, ref: str
) -> tuple[dict[str, Any], bool]:
    cnr, order_no, order_date_s = ref.split("|", 2)
    order_date = date.fromisoformat(order_date_s)
    case = session.scalar(select(Case).where(Case.cnr == cnr))
    if case is None:
        return {"error": "no such case"}, True
    order = session.scalar(
        select(Order).where(
            Order.case_id == case.id, Order.order_no == order_no, Order.order_date == order_date
        )
    )
    if order is None:
        return {"error": "no such order"}, True
    if order.document_id is not None:
        return {"document_id": str(order.document_id), "already": True}, False
    order.download_attempts = (order.download_attempts or 0) + 1
    try:
        pdf = await hc.show_order(cnr, order_no, order_date)
    except NapixNotFound as exc:
        order.download_status, order.last_error = DownloadStatus.NOT_AVAILABLE, str(exc)[:500]
        session.flush()
        return {"error": "not available (628)"}, True
    if not isinstance(pdf, bytes):
        order.download_status, order.last_error = DownloadStatus.FAILED, f"not a PDF: {str(pdf)[:200]}"
        session.flush()
        raise RuntimeError(order.last_error)
    stored = store.put(pdf, "application/pdf")
    # by sha256 *and* kind (design documents-uploads, decision 8): an order never points at a user's upload
    doc = session.scalar(
        select(Document).where(Document.sha256 == stored.sha256, Document.kind == DocKind.ORDER)
    )
    new = doc is None
    if doc is None:
        doc = Document(
            sha256=stored.sha256,
            storage_key=stored.key,
            mime="application/pdf",
            size_bytes=stored.size,
            kind=DocKind.ORDER,
            doc_type=DocType.JUDGMENT if order.kind == OrderKind.JUDGMENT else DocType.ORDER,
            doc_group=DocGroup.COURT_RECORD,
            case_id=case.id,
            doc_date=order_date,
            description=f"{order.order_details or order.kind.value} {order_no} of {order_date} in {case.case_no_text or cnr}",
            visibility=Visibility.CASE_SCOPE,
            virus_scan_status=ScanStatus.SKIPPED,
            text_status=TextStatus.PENDING,
            sourcetrace_status=SourcetraceStatus.PENDING,
        )
        session.add(doc)
        session.flush()
    order.document_id = doc.id
    order.download_status = DownloadStatus.STORED
    order.last_error = None
    emit_event(
        session,
        EventType.ORDER_STORED,
        case,
        {"cnr": cnr, "order_no": order_no, "order_date": order_date, "document_id": str(doc.id)},
        dedupe=f"order_stored:{cnr}:{order_no}:{order_date}",
    )
    session.flush()
    return {
        "document_id": str(doc.id),
        "new": new,
        "size": stored.size,
        "stored_at": datetime.now(UTC).isoformat(),
    }, False
