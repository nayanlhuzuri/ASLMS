"""Shared helpers for the SourceTrace tests (design `sourcetrace-connector`): documents written the way the
pipeline and the upload service write them, and a run of the ingestion loop against `FakeSourceTrace`."""

from __future__ import annotations

import asyncio
from datetime import date

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aslms.domain.cases import Case
from aslms.domain.documents import (
    DocGroup,
    DocKind,
    Document,
    ScanStatus,
    SourcetraceStatus,
    TextStatus,
    Visibility,
)
from aslms.domain.org import Office
from aslms.domain.reference import DocType, RecordType
from aslms.domain.workflow import SourcetraceIngestion
from aslms.integration.sourcetrace.fake import FakeSourceTrace
from aslms.services import sourcetrace_ingest as st
from aslms.services.documents import sourcetrace_status_for
from aslms.services.refno import allocate_ref_no
from aslms.services.storage import LocalStore
from tests import samplefiles as sf

CONFIG = st.IngestConfig(batch=50, run_seconds=60.0, timeout_seconds=0.2, max_attempts=5)


def upload_row(
    s: Session,
    store: LocalStore,
    case: Case,
    office: Office,
    *,
    text: str = "a filing",
    doc_type: DocType = DocType.PETITION,
    group: DocGroup = DocGroup.COURT_FILING,
    visibility: Visibility = Visibility.CASE_SCOPE,
    kind: DocKind = DocKind.UPLOAD,
    doc_date: date = date(2025, 1, 3),
    description: str = "Writ petition as filed",
    original_filename: str = "petition.pdf",
) -> Document:
    """A user file as `documents.create_document` writes it (no audit, no event: the ingestion tests only need
    the row and the stored bytes)."""
    data = sf.text_pdf([text])
    stored = store.put(data, "application/pdf")
    doc = Document(
        ref_no=allocate_ref_no(s, office.code, RecordType.DOC.value),
        sha256=stored.sha256,
        storage_key=stored.key,
        mime="application/pdf",
        size_bytes=stored.size,
        original_filename=original_filename,
        kind=kind,
        doc_type=doc_type,
        doc_group=group,
        case_id=case.id if kind != DocKind.ADMIN else None,
        doc_date=doc_date,
        description=description,
        visibility=visibility,
        office_id=office.id,
        virus_scan_status=ScanStatus.CLEAN,
        text_status=TextStatus.PENDING,
        sourcetrace_status=sourcetrace_status_for(group, visibility),
        actor_name="Test Uploader",
        actor_office_code=office.code,
    )
    s.add(doc)
    s.flush()
    return doc


def ingest(world, store: LocalStore, fake: FakeSourceTrace, config: st.IngestConfig = CONFIG, **kw) -> dict:
    return asyncio.run(st.ingest_pending(world.Session, fake, store, config, **kw))


def doc(world, doc_id) -> Document:
    with world.Session() as s:
        return s.get(Document, doc_id)


def attempts(world, doc_id) -> list[SourcetraceIngestion]:
    with world.Session() as s:
        return list(
            s.scalars(
                sa.select(SourcetraceIngestion)
                .where(SourcetraceIngestion.document_id == doc_id)
                .order_by(SourcetraceIngestion.created_at, SourcetraceIngestion.attempt)
            ).all()
        )


def make_due(world, doc_id) -> None:
    """Back-off elapsed: the document may be claimed again."""
    with world.Session() as s:
        s.execute(
            sa.update(Document)
            .where(Document.id == doc_id)
            .values(sourcetrace_next_at=sa.func.now() - sa.text("interval '1 minute'"))
        )
        s.commit()


def status_of(world, doc_id) -> str:
    return SourcetraceStatus(doc(world, doc_id).sourcetrace_status).value
