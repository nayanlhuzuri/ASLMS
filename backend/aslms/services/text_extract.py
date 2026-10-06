"""Text extraction for documents (design `documents-uploads`, decision 10): PDFs through `pymupdf`, DOCX
through `zipfile` + `xml.etree`; DOC and images get no text (no OCR). `extract` is pure over bytes;
`extract_document` writes the `document_text` row and the document's status columns; `extract_pending`
claims a batch with `FOR UPDATE SKIP LOCKED`, one savepoint per document, and records failures in
`source_failures` (`kind = text_extraction`). Runs in the worker, never in an API request."""

from __future__ import annotations

import io
import logging
import re
import uuid
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from aslms.domain.documents import Document, DocumentText, ScanStatus, TextStatus
from aslms.services.filetypes import DOCX_MIME, PDF_MIME
from aslms.services.matching import record_failure
from aslms.services.storage import LocalStore

log = logging.getLogger(__name__)

MAX_PAGES = 2000
MIN_CHARS_PER_PAGE = 20  # below this average a PDF is a scan without a text layer
MAX_DOCX_UNCOMPRESSED = 50 * 1024 * 1024
SEARCH_VECTOR_CHARS = 500_000  # keeps the tsvector under its 1 MB limit
FAILURE_KIND = "text_extraction"
WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@dataclass(frozen=True)
class Extracted:
    text: str | None
    page_count: int | None
    status: TextStatus
    error: str | None = None


def _extract_pdf(data: bytes) -> Extracted:
    import pymupdf

    with pymupdf.open(stream=data, filetype="pdf") as pdf:
        page_count = pdf.page_count
        pages = []
        for i, page in enumerate(pdf):
            if i >= MAX_PAGES:
                break
            pages.append(page.get_text("text") or "")
    full = "\n\f".join(pages).strip()
    looked_at = max(1, min(page_count, MAX_PAGES))
    non_space = len(re.sub(r"\s", "", full))
    if non_space / looked_at < MIN_CHARS_PER_PAGE:
        return Extracted(full or None, page_count, TextStatus.NONE)
    return Extracted(full, page_count, TextStatus.EXTRACTED)


def _extract_docx(data: bytes) -> Extracted:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        info = zf.getinfo("word/document.xml")
        total = sum(i.file_size for i in zf.infolist())
        if info.file_size > MAX_DOCX_UNCOMPRESSED or total > MAX_DOCX_UNCOMPRESSED:
            return Extracted(None, None, TextStatus.FAILED, "document.xml declares more than 50 MB")
        xml = zf.read("word/document.xml")
    root = ET.fromstring(xml)
    paragraphs = []
    for p in root.iter(f"{WORD_NS}p"):
        parts = [t.text or "" for t in p.iter(f"{WORD_NS}t")]
        paragraphs.append("".join(parts))
    full = "\n".join(paragraphs).strip()
    return Extracted(full or None, None, TextStatus.EXTRACTED if full else TextStatus.NONE)


def extract(data: bytes, mime: str) -> Extracted:
    """Pure: the text, page count and status for `data` of type `mime`; never raises."""
    try:
        if mime == PDF_MIME:
            return _extract_pdf(data)
        if mime == DOCX_MIME:
            return _extract_docx(data)
        return Extracted(None, None, TextStatus.NONE)
    except Exception as exc:  # noqa: BLE001 — a hostile or corrupt file is a recorded failure
        return Extracted(None, None, TextStatus.FAILED, f"{exc.__class__.__name__}: {exc}"[:500])


# ------------------------------------------------------------------------------------------------ database


def _write_text(session: Session, doc: Document, result: Extracted) -> None:
    row = session.get(DocumentText, doc.id)
    if row is None:
        row = DocumentText(document_id=doc.id)
        session.add(row)
    row.full_text = result.text
    row.page_count = result.page_count
    row.search_vector = (
        func.to_tsvector("english", func.left(result.text, SEARCH_VECTOR_CHARS)) if result.text else None
    )
    session.flush()


def extract_document(session: Session, store: LocalStore, doc: Document) -> TextStatus:
    """Extracts one document's text and writes the result; a failure is recorded, never raised."""
    try:
        data = store.get(doc.storage_key)
    except OSError as exc:
        result = Extracted(None, None, TextStatus.FAILED, f"file missing from the store: {exc}"[:500])
    else:
        result = extract(data, doc.mime)
    now = datetime.now(UTC)
    if result.status == TextStatus.FAILED:
        doc.text_status = TextStatus.FAILED
        record_failure(session, FAILURE_KIND, str(doc.id), result.error or "extraction failed")
    else:
        _write_text(session, doc, result)
        doc.text_status = result.status
        doc.text_extracted_at = now
        if result.page_count is not None:
            doc.page_count = result.page_count
        session.execute(
            sql_text(
                "UPDATE source_failures SET resolved_at = now() WHERE kind = :k AND ref = :r AND resolved_at IS NULL"
            ),
            {"k": FAILURE_KIND, "r": str(doc.id)},
        )
    session.flush()
    return doc.text_status


def pending_condition(*, retry_failed: bool = False):
    statuses = [TextStatus.PENDING] + ([TextStatus.FAILED] if retry_failed else [])
    return (
        Document.text_status.in_(statuses),
        Document.virus_scan_status.in_([ScanStatus.CLEAN, ScanStatus.SKIPPED]),
        Document.mime.in_([PDF_MIME, DOCX_MIME]),
    )


def extract_pending(
    session: Session,
    store: LocalStore,
    *,
    batch: int = 50,
    retry_failed: bool = False,
    document_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """A batch of pending documents, claimed with `FOR UPDATE SKIP LOCKED` so two runs never share one;
    one savepoint per document. Returns the counters `claimed`, `extracted`, `none`, `failed`."""
    stmt = select(Document).where(*pending_condition(retry_failed=retry_failed))
    if document_id is not None:
        stmt = stmt.where(Document.id == document_id)
    stmt = stmt.order_by(Document.created_at).limit(max(1, int(batch))).with_for_update(skip_locked=True)
    docs = list(session.scalars(stmt).all())
    counters: dict[str, Any] = {"claimed": len(docs), "extracted": 0, "none": 0, "failed": 0}
    for doc in docs:
        with session.begin_nested():
            status = extract_document(session, store, doc)
        counters[status.value] = counters.get(status.value, 0) + 1
    return counters
