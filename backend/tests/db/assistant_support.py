"""Shared helpers for the Case Assistant tests (design `assistant`): court orders and court filings with stored text
written through `document_text` (pages joined with "\\n\\f", as text extraction writes them), documents of the kinds
that must never be cited, and a question asked through the service with the preview or the fake."""

from __future__ import annotations

import asyncio
from datetime import date

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aslms.core.config import Settings
from aslms.domain.assistant import AssistantMessage
from aslms.domain.cases import Case
from aslms.domain.documents import (
    DocGroup,
    DocKind,
    Document,
    DocumentText,
    Order,
    OrderKind,
    ScanStatus,
    SourcetraceStatus,
    TextStatus,
    Visibility,
)
from aslms.domain.org import Office
from aslms.domain.reference import DocType
from aslms.services import assistant as svc
from aslms.services.assistant_preview import PreviewConnector
from aslms.services.storage import LocalStore
from tests import samplefiles as sf
from tests.db import docs_support as ds
from tests.db import st_support

CONFIG = svc.AssistantConfig(timeout_seconds=10.0, retry_delay=0.01)


def set_text(s: Session, doc: Document, pages: list[str]) -> None:
    full = "\n\f".join(pages)
    row = s.get(DocumentText, doc.id)
    if row is None:
        row = DocumentText(document_id=doc.id)
        s.add(row)
    row.full_text = full
    row.page_count = len(pages)
    row.search_vector = sa.func.to_tsvector("english", full)
    doc.text_status = TextStatus.EXTRACTED
    s.flush()


def order(
    s: Session,
    store: LocalStore,
    case: Case,
    pages: list[str],
    *,
    order_no: str = "1",
    order_date: date = date(2026, 3, 12),
    kind: OrderKind = OrderKind.INTERIM,
) -> tuple[Order, Document]:
    """A stored court order whose PDF is unique (its own bytes) and whose stored text is `pages`."""
    o, doc = ds.stored_order(
        s,
        store,
        case,
        sf.text_pdf([f"{case.case_no_text} order {order_no} {order_date}"] + pages[:1]),
        order_no=order_no,
        order_date=order_date,
        kind=kind,
    )
    set_text(s, doc, pages)
    return o, doc


def filing(
    s: Session,
    store: LocalStore,
    case: Case,
    office: Office,
    pages: list[str],
    *,
    visibility: Visibility = Visibility.CASE_SCOPE,
    group: DocGroup = DocGroup.COURT_FILING,
    kind: DocKind = DocKind.UPLOAD,
    doc_type: DocType = DocType.PETITION,
    doc_date: date = date(2026, 2, 1),
    ingested_ref: str | None = None,
) -> Document:
    doc = st_support.upload_row(
        s,
        store,
        case,
        office,
        text=pages[0],
        doc_type=doc_type,
        group=group,
        visibility=visibility,
        kind=kind,
        doc_date=doc_date,
    )
    set_text(s, doc, pages)
    if ingested_ref:
        ingest(s, doc, ingested_ref)
    return doc


def ingest(s: Session, doc: Document, ref: str) -> None:
    doc.sourcetrace_status = SourcetraceStatus.INGESTED
    doc.sourcetrace_ref = ref
    doc.sourcetrace_ingested_at = sa.func.now()
    s.flush()


def causelist_doc(s: Session, store: LocalStore, pages: list[str]) -> Document:
    data = sf.text_pdf(pages[:1] + ["cause list"])
    stored = store.put(data, "application/pdf")
    doc = Document(
        sha256=stored.sha256,
        storage_key=stored.key,
        mime="application/pdf",
        size_bytes=stored.size,
        kind=DocKind.CAUSELIST,
        doc_type=DocType.CAUSELIST,
        doc_group=DocGroup.COURT_RECORD,
        doc_date=date(2026, 3, 1),
        visibility=Visibility.CASE_SCOPE,
        virus_scan_status=ScanStatus.SKIPPED,
        text_status=TextStatus.PENDING,
    )
    s.add(doc)
    s.flush()
    set_text(s, doc, pages)
    return doc


def preview(world, **settings) -> PreviewConnector:
    return PreviewConnector(world.Session, Settings(_env_file=None, **settings))


def ask(world, key: str, question: str, scope: str, *, case=None, connector=None, config=CONFIG, **kw):
    with world.Session() as s:
        actor, user = world.actor(s, key)
    return asyncio.run(
        svc.ask(
            world.Session,
            actor,
            user,
            question=question,
            scope=scope,
            case=case,
            connector=connector if connector is not None else preview(world),
            config=config,
            **kw,
        )
    )


def answer(world, result) -> AssistantMessage:
    with world.Session() as s:
        return s.get(AssistantMessage, result.answer_id)


def read(world, key: str, result_or_id) -> dict:
    """The answer as `MessageOut`, read as `key`."""
    msg_id = getattr(result_or_id, "answer_id", result_or_id)
    with world.Session() as s:
        return svc.message(s, world.user(s, key), msg_id)


def cited_docs(world, result) -> set:
    return {c["document_id"] for c in (answer(world, result).citations or [])}
