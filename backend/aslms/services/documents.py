"""Case documents uploaded by users (plan §5.6): type, date, description, uploader and office; PDF, Word and
images only; size limit; virus scan before storage (ground rule 9); per-document visibility.

Visibility of a document to a principal who can see the case's contents:
  case_scope         everyone in the case scope, except standing counsel
  counsel_shared     everyone in the case scope, including standing counsel
  private_to_office  users of the uploading office (and offices below it), and the State tier
  court records (orders, cause lists) are visible to everyone in the case scope."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement

from aslms.core.config import get_settings
from aslms.core.errors import ValidationError
from aslms.core.time import now_utc
from aslms.domain.cases import Case
from aslms.domain.documents import (
    DocGroup,
    DocType,
    Document,
    DocumentKind,
    SourceTraceStatus,
    TextStatus,
    VirusScanStatus,
    Visibility,
)
from aslms.domain.events import EventType
from aslms.domain.org import Office, Role
from aslms.integration.antivirus import get_scanner
from aslms.services import audit, events, storage
from aslms.services.audit import Actor
from aslms.services.scope import Principal

ALLOWED = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}
MAGIC = {
    "application/pdf": (b"%PDF",),
    "application/msword": (b"\xd0\xcf\x11\xe0",),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (b"PK\x03\x04",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG",),
    "image/tiff": (b"II*\x00", b"MM\x00*"),
}
COURT_FILING_TYPES = {
    DocType.WRIT_PETITION,
    DocType.AFFIDAVIT_IN_OPPOSITION,
    DocType.REPLY,
    DocType.REJOINDER,
    DocType.IA,
    DocType.ANNEXURE,
    DocType.COMPLIANCE_REPORT,
}
INTERNAL_TYPES = {DocType.PARAWISE_COMMENTS, DocType.INSTRUCTIONS_TO_COUNSEL}
UPLOADABLE_TYPES = COURT_FILING_TYPES | INTERNAL_TYPES | {DocType.OTHER}


@dataclass(frozen=True)
class UploadRequest:
    filename: str
    content: bytes
    doc_type: DocType
    doc_date: date | None
    description: str | None
    visibility: Visibility
    internal: bool | None = None  # only meaningful for DocType.OTHER


def group_for(doc_type: DocType, internal: bool | None) -> DocGroup:
    if doc_type in COURT_FILING_TYPES:
        return DocGroup.COURT_FILING
    if doc_type in INTERNAL_TYPES:
        return DocGroup.INTERNAL
    return DocGroup.INTERNAL if internal is not False else DocGroup.COURT_FILING


def validate(req: UploadRequest) -> str:
    ext = "." + req.filename.rsplit(".", 1)[-1].lower() if "." in req.filename else ""
    mime = ALLOWED.get(ext)
    if not mime:
        raise ValidationError("only PDF, Word and image files are accepted", filename=req.filename)
    limit = get_settings().upload_max_mb * 1024 * 1024
    if not req.content:
        raise ValidationError("the file is empty")
    if len(req.content) > limit:
        raise ValidationError(f"the file is larger than {get_settings().upload_max_mb} MB")
    if not any(req.content.startswith(m) for m in MAGIC[mime]):
        raise ValidationError("the file content does not match its type", filename=req.filename)
    if req.doc_type not in UPLOADABLE_TYPES:
        raise ValidationError("this document type cannot be uploaded", doc_type=req.doc_type.value)
    return mime


def upload(session: Session, actor: Actor, principal: Principal, case: Case, req: UploadRequest) -> Document:
    mime = validate(req)
    status, detail = get_scanner().scan(req.content)
    if status == "infected":
        audit.record(
            session,
            actor,
            "document.rejected_infected",
            "case",
            case.id,
            case_id=case.id,
            after={"filename": req.filename, "signature": detail},
        )
        raise ValidationError("the file was rejected by the virus scan", signature=detail)
    if status == "failed" and get_settings().is_prod:
        raise ValidationError("the virus scanner is unavailable; try again later")
    group = group_for(req.doc_type, req.internal)
    sha = storage.sha256_bytes(req.content)
    existing = session.scalar(select(Document).where(Document.sha256 == sha))
    if existing:
        # same bytes already stored (possibly for another case): keep one blob, record a new link-free row is not
        # possible with a unique sha, so reuse the row only if it belongs to this case
        if existing.case_id == case.id:
            return existing
        raise ValidationError(
            "this exact file is already stored for another case", case_id=str(existing.case_id)
        )
    sha, key = storage.write_blob(req.content, "uploads", mime)
    doc = Document(
        sha256=sha,
        storage_key=key,
        mime=mime,
        size_bytes=len(req.content),
        original_filename=req.filename[:300],
        kind=DocumentKind.COURT_FILING if group == DocGroup.COURT_FILING else DocumentKind.INTERNAL,
        doc_type=req.doc_type,
        doc_group=group,
        case_id=case.id,
        doc_date=req.doc_date,
        description=(req.description or "")[:2000] or None,
        visibility=req.visibility,
        office_id=principal.office_id,
        virus_scan_status=VirusScanStatus(status),
        scanned_at=now_utc(),
        text_status=TextStatus.PENDING if mime == "application/pdf" else TextStatus.NOT_APPLICABLE,
        # court filings become SourceTrace candidates when the connector exists (Phase 2); internal never
        sourcetrace_status=SourceTraceStatus.NOT_APPLICABLE,
        **actor.snapshot(),
    )
    session.add(doc)
    session.flush()
    events.emit(
        session,
        EventType.DOCUMENT_UPLOADED,
        f"doc:{doc.id}",
        case_id=case.id,
        actor_user_id=actor.user_id,
        payload={
            "document_id": str(doc.id),
            "doc_type": req.doc_type.value,
            "group": group.value,
            "visibility": req.visibility.value,
            "filename": req.filename,
        },
    )
    audit.record(
        session,
        actor,
        "document.upload",
        "document",
        doc.id,
        case_id=case.id,
        after={
            "filename": req.filename,
            "doc_type": req.doc_type.value,
            "visibility": req.visibility.value,
            "scan": status,
        },
    )
    if mime == "application/pdf":
        from aslms.services.orders import extract_text

        extract_text(session, doc)
    return doc


def document_visibility_clause(p: Principal) -> ColumnElement[bool]:
    """Applied on top of the case scope."""
    court_record = Document.doc_group == DocGroup.COURT_RECORD
    if p.is_state_tier:
        return Document.id.isnot(None)
    my_office = select(Office.id).where(
        or_(Office.path == p.office_path, Office.path.like(p.office_path + "/%"))
    )
    private_ok = and_(Document.visibility == Visibility.PRIVATE_TO_OFFICE, Document.office_id.in_(my_office))
    if p.role == Role.STANDING_COUNSEL:
        return or_(court_record, Document.visibility == Visibility.COUNSEL_SHARED)
    return or_(
        court_record, Document.visibility.in_([Visibility.CASE_SCOPE, Visibility.COUNSEL_SHARED]), private_ok
    )


def get_visible(session: Session, p: Principal, document_id: uuid.UUID) -> Document | None:
    from aslms.services.scope import case_scope_clause

    return session.scalar(
        select(Document)
        .join(Case, Case.id == Document.case_id)
        .where(Document.id == document_id, case_scope_clause(p), document_visibility_clause(p))
    )
