"""Orders archive (plan §5.6) and next dates from orders (§5.5, §6.2).

Download: pending orders of tracked cases are fetched through Show Order, stored (sha256) and linked.
Text: PyMuPDF text layer → document_text (scanned orders without a text layer are marked `failed`; OCR is not
configured). Next date: a date stated in the most recent order ("list on 15.10.2026", "fixed on 3rd November,
2026") is read directly (Phase 1). A period ("after two weeks") or an unclear direction is flagged for manual
review; reading periods through SourceTrace arrives in Phase 2."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import date, timedelta

import pymupdf
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from aslms.core.errors import IntegrationError, SourceNotFound
from aslms.core.time import now_utc
from aslms.domain.alerts import NextDateSource
from aslms.domain.cases import Case
from aslms.domain.documents import (
    DocType,
    Document,
    DocumentKind,
    DocumentText,
    DownloadStatus,
    Order,
    OrderKind,
    TextStatus,
)
from aslms.domain.ops import FailureKind
from aslms.integration.base import OrderRef
from aslms.services import cases as case_svc
from aslms.services import ops, storage

MONTHS = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1
    )
}
LIST_VERBS = (
    r"(?:list(?:ed)?|fix(?:ed)?|post(?:ed)?|come\s+up|put\s+up|place(?:d)?|re-?list(?:ed)?|call(?:ed)?)"
)
NUMERIC_DATE = r"(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})"
WORD_DATE = r"(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([A-Za-z]{3,9})[,.]?\s+(\d{4})"
SPECIFIC_RE = re.compile(rf"{LIST_VERBS}[^.;]{{0,80}}?\bon\s+(?:{NUMERIC_DATE}|{WORD_DATE})", re.I)
PERIOD_RE = re.compile(
    r"\b(?:after|within|in)\s+(\d+|one|two|three|four|five|six|seven|eight|ten|twelve)\s*(?:\(\w+\)\s*)?(days?|weeks?|months?)\b",
    re.I,
)
WORD_NUM = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "ten": 10,
    "twelve": 12,
}


@dataclass(frozen=True)
class NextDateReading:
    kind: str  # specific | period | none
    next_date: date | None
    snippet: str | None
    period_days: int | None = None


def _mk_date(d: str, m: str, y: str) -> date | None:
    try:
        year = int(y) + (2000 if len(y) == 2 else 0)
        month = int(m) if m.isdigit() else MONTHS.get(m[:3].lower())
        return date(year, month, int(d)) if month else None
    except (ValueError, TypeError):
        return None


def read_next_date(order_text: str, order_date: date | None) -> NextDateReading:
    """Pure: finds the next-date direction in an order's text. Specific dates must fall after the order date."""
    t = re.sub(r"\s+", " ", order_text or "")
    found: list[tuple[date, str]] = []
    for m in SPECIFIC_RE.finditer(t):
        g = m.groups()
        d = _mk_date(g[0], g[1], g[2]) if g[0] else _mk_date(g[3], g[4], g[5])
        if d and (order_date is None or d > order_date) and d.year < 2100:
            found.append((d, t[max(0, m.start() - 20) : m.end() + 10].strip()))
    if found:
        d, snip = found[-1]  # the last direction in the order is the operative one
        return NextDateReading("specific", d, snip)
    periods = list(PERIOD_RE.finditer(t))
    pm = periods[-1] if periods else None
    if pm and order_date:
        n = int(pm.group(1)) if pm.group(1).isdigit() else WORD_NUM.get(pm.group(1).lower(), 0)
        unit = pm.group(2).lower()
        days = n * (7 if unit.startswith("week") else 30 if unit.startswith("month") else 1)
        return NextDateReading("period", None, t[max(0, pm.start() - 60) : pm.end() + 20].strip(), days)
    return NextDateReading("none", None, None)


def extract_text(session: Session, doc: Document) -> DocumentText | None:
    if doc.mime != "application/pdf":
        doc.text_status = TextStatus.NOT_APPLICABLE
        return None
    try:
        with pymupdf.open(stream=storage.read_blob(doc.storage_key), filetype="pdf") as pdf:
            pages = [p.get_text() for p in pdf]
    except Exception as e:  # noqa: BLE001 — corrupt PDFs are recorded, not fatal
        doc.text_status = TextStatus.FAILED
        ops.record_failure(
            session, FailureKind.ORDER_DOWNLOAD, f"text:{doc.id}", f"text extraction failed: {e}"
        )
        return None
    full = "\n".join(pages).strip()
    doc.text_extracted_at = now_utc()
    if not full:
        doc.text_status = TextStatus.FAILED  # scanned PDF without a text layer; OCR not configured
        return None
    existing = session.get(DocumentText, doc.id)
    dt = existing or DocumentText(document_id=doc.id, full_text=full, page_count=len(pages))
    dt.full_text, dt.page_count = full, len(pages)
    if not existing:
        session.add(dt)
    session.flush()
    session.execute(
        text(
            "UPDATE document_text SET search_vector = to_tsvector('english', left(full_text, 900000)) WHERE document_id = :id"
        ),
        {"id": doc.id},
    )
    doc.text_status = TextStatus.DONE
    return dt


def apply_next_date_from_order(
    session: Session, case: Case, order: Order, order_text: str
) -> NextDateReading:
    latest = session.scalar(
        select(Order)
        .where(Order.case_id == case.id)
        .order_by(Order.order_date.desc(), Order.order_no.desc())
        .limit(1)
    )
    reading = read_next_date(order_text, order.order_date)
    if latest is None or latest.id != order.id:
        return reading  # only the most recent order sets the next date
    if reading.kind == "specific":
        case_svc.record_next_date(
            session,
            case,
            reading.next_date,
            NextDateSource.ORDER_SPECIFIC,
            order_id=order.id,
            confidence=0.9,
            note=reading.snippet,
        )
    elif reading.kind == "period":
        # the counted date is a hint only; a person confirms it (SourceTrace takes over in Phase 2)
        hint = order.order_date + timedelta(days=reading.period_days or 0)
        case_svc.record_next_date(
            session,
            case,
            hint,
            NextDateSource.MANUAL,
            order_id=order.id,
            confidence=0.3,
            needs_review=True,
            note=f"period direction: {reading.snippet}",
        )
    return reading


def store_order_pdf(session: Session, order: Order, data: bytes) -> Document:
    case = session.get(Case, order.case_id)
    doc, _ = storage.store_system_document(
        session,
        data,
        kind=DocumentKind.COURT_ORDER,
        doc_type=DocType.JUDGMENT if order.kind in (OrderKind.FINAL, OrderKind.JUDGMENT) else DocType.ORDER,
        filename=f"{(case.cnr or case.id)}_{order.order_no}_{order.order_date}.pdf",
        case_id=case.id,
        doc_date=order.order_date,
        description=f"{order.kind.value} order no. {order.order_no} dated {order.order_date:%d-%m-%Y}",
    )
    order.document_id, order.download_status, order.last_error = doc.id, DownloadStatus.DOWNLOADED, None
    dt = extract_text(session, doc)
    if dt:
        apply_next_date_from_order(session, case, order, dt.full_text)
    return doc


def pending_orders(session: Session, limit: int) -> list[Order]:
    return list(
        session.scalars(
            select(Order)
            .join(Case, Case.id == Order.case_id)
            .where(
                Order.download_status.in_([DownloadStatus.PENDING, DownloadStatus.FAILED]),
                Order.download_attempts < 5,
                Case.is_tracked.is_(True),
                Case.cnr.isnot(None),
            )
            .order_by(Order.order_date.desc())
            .limit(limit)
        )
    )


def download_pending(session: Session, source, limit: int = 200) -> dict[str, int]:
    """`source` is a CourtSource (NapixHighCourt). Runs the async calls in a private loop."""
    counts = {"downloaded": 0, "not_available": 0, "failed": 0}
    for order in pending_orders(session, limit):
        case = session.get(Case, order.case_id)
        ref = OrderRef(order.order_no, order.order_date, order.kind.value, order.raw or {})
        order.download_attempts += 1
        try:
            data = asyncio.run(source.order_pdf(case.cnr, ref))
        except SourceNotFound:
            data = None
        except IntegrationError as e:
            order.download_status, order.last_error = DownloadStatus.FAILED, str(e)[:500]
            ops.record_failure(
                session, FailureKind.ORDER_DOWNLOAD, f"{case.cnr}:{order.order_no}:{order.order_date}", str(e)
            )
            counts["failed"] += 1
            continue
        if not data:
            order.download_status = DownloadStatus.NOT_AVAILABLE
            counts["not_available"] += 1
            continue
        store_order_pdf(session, order, data)
        ops.resolve_failure(
            session, FailureKind.ORDER_DOWNLOAD, f"{case.cnr}:{order.order_no}:{order.order_date}"
        )
        counts["downloaded"] += 1
    return counts
