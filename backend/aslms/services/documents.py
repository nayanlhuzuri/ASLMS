"""Case documents (design `documents-uploads`): upload after a clean virus scan, the Documents tab, metadata,
file serving, order PDFs, visibility changes and archiving, the uploadable types and the content search.
Every read applies `visibility.document_visible_condition` in SQL (nothing is filtered after the query);
every write audits. No delete: after upload only the visibility and the archive flag can change.

Memberships (design `user-memberships`, decisions 6 and 20): a case upload is written by the caller's
membership with a working basis on the case that holds `documents.upload` (the `DOC` number and the office come
from it); kind `admin` stores the supporting document of an admin ticket — no case, no working-relation check,
the ticket kind's types only, group `internal`, `private_to_office`, no case-timeline event."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Select, func, or_, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from aslms.core.clock import today_ist
from aslms.domain.cases import Case
from aslms.domain.documents import (
    DocGroup,
    DocKind,
    Document,
    DocumentText,
    Order,
    ScanStatus,
    SourcetraceStatus,
    TextStatus,
    Visibility,
)
from aslms.domain.org import Office, User
from aslms.domain.reference import DocType, EventType, Permission, RecordType, RefDocType
from aslms.services import access, inbox, visibility
from aslms.services.access import Member
from aslms.services.audit import Actor, write_audit
from aslms.services.cases import CaseNotFound, emit_event, ref_no_from_url, resolve_case_ref
from aslms.services.filetypes import INLINE_MIMES, EmptyFile, TypeNotAllowed, detect, safe_filename
from aslms.services.matching import record_failure
from aslms.services.refno import allocate_ref_no
from aslms.services.scanner import Scanner, ScannerUnavailable
from aslms.services.storage import EXT_FOR_MIME, LocalStore
from aslms.services.visibility import (
    NotVisibleCase,
    NotVisibleDocument,
    access_basis,
    acting_member_for_case,
    document_visible_condition,
    require_visible,
    require_visible_document,
)

SYSTEM_TYPES = frozenset({DocType.CAUSELIST, DocType.ORDER, DocType.JUDGMENT})
ADMIN_TYPES = frozenset({DocType.GOVERNMENT_ORDER})  # supporting documents of admin tickets, never of a case
USER_KINDS = (DocKind.UPLOAD, DocKind.ATTACHMENT)
WRITE_KINDS = (DocKind.UPLOAD, DocKind.ATTACHMENT, DocKind.ADMIN)
EARLIEST_DOC_DATE = date(1950, 1, 1)
MIN_TEXT, MAX_TEXT = 3, 500
MAX_SEARCH_LIMIT = 50
MIN_QUERY = 3
MISSING_FILE_KIND = "document_missing"


class DocumentError(ValueError):
    """A refused change (HTTP 400 unless the subclass says otherwise)."""

    code = "bad_request"
    http_status = 400


class UploadRefused(DocumentError):
    """`code`: bad_field (400), not_working_on_case (403), too_large (413), type_not_allowed (415),
    infected (422), scanner_unavailable (503), duplicate (409). `audited`: a `document.upload_rejected` row
    was written (the router commits it before answering)."""

    STATUS = {
        "bad_field": 400,
        "not_working_on_case": 403,
        "duplicate": 409,
        "too_large": 413,
        "type_not_allowed": 415,
        "infected": 422,
        "scanner_unavailable": 503,
    }

    def __init__(self, code: str, message: str, *, audited: bool = False, extra: dict | None = None):
        super().__init__(message)
        self.code = code
        self.http_status = self.STATUS[code]
        self.audited = audited
        self.extra = extra or {}


class NotAllowed(DocumentError):
    code, http_status = "forbidden", 403


class AlreadyIngested(DocumentError):
    code, http_status = "already_ingested", 409


class DocumentBusy(DocumentError):
    """Design sourcetrace-connector, decision 6: the row is locked by a send to SourceTrace in flight."""

    code, http_status = "document_busy", 409


class InlineNotSupported(DocumentError):
    code, http_status = "inline_not_supported", 400


class AttachmentFollowsNote(DocumentError):
    """Design custody-workflow, decision 18: an attachment's visibility and archive state follow its note."""

    code, http_status = "attachment_follows_note", 409


def _not_attachment(doc: Document) -> None:
    if DocKind(doc.kind) == DocKind.ATTACHMENT:
        raise AttachmentFollowsNote(
            "an attachment follows its note; its visibility and archive state cannot be changed"
        )


class OrderNotStored(LookupError):
    def __init__(self, download_status: str):
        super().__init__("the order's PDF is not stored")
        self.download_status = download_status


class FileMissing(RuntimeError):
    """The row exists but the stored file is gone (HTTP 500; a `source_failures` row)."""


@dataclass
class Page:
    items: list[dict[str, Any]] = field(default_factory=list)
    total: int = 0


@dataclass(frozen=True)
class ServedFile:
    path: Path
    mime: str
    filename: str
    size: int
    disposition: str


def _now() -> datetime:
    return datetime.now(UTC)


def _value(v: Any) -> Any:
    return v.value if hasattr(v, "value") and not isinstance(v, bool | int | float | str) else v


# ------------------------------------------------------------------------------------------------ rules


def sourcetrace_status_for(group: DocGroup, vis: Visibility) -> SourcetraceStatus:
    """Decision 9: internal never; a court filing kept private is not sent until it is widened."""
    if group == DocGroup.INTERNAL or vis == Visibility.PRIVATE_TO_OFFICE:
        return SourcetraceStatus.NOT_APPLICABLE
    return SourcetraceStatus.PENDING


def _text_status_for(mime: str) -> TextStatus:
    from aslms.services.filetypes import DOCX_MIME, PDF_MIME

    return TextStatus.PENDING if mime in (PDF_MIME, DOCX_MIME) else TextStatus.NONE


def _clean_text(value: str | None, name: str) -> str:
    s = (value or "").strip()
    if not MIN_TEXT <= len(s) <= MAX_TEXT:
        raise UploadRefused("bad_field", f"{name} must be {MIN_TEXT} to {MAX_TEXT} characters")
    return s


def _doc_type(session: Session, code: str | None, allowed: frozenset[DocType] | None = None) -> RefDocType:
    """A case upload never takes a system type or an admin type; an `admin` document takes only `allowed`."""
    try:
        member = DocType(str(code or "").strip().lower())
    except ValueError as exc:
        raise UploadRefused("bad_field", f"unknown doc_type {code!r}") from exc
    row = session.get(RefDocType, member.value)
    refused = (
        member not in allowed if allowed is not None else (member in SYSTEM_TYPES or member in ADMIN_TYPES)
    )
    if row is None or not row.is_active or refused:
        raise UploadRefused("bad_field", f"doc_type {member.value} cannot be uploaded here")
    return row


def _group_for(row: RefDocType, doc_group: str | None) -> DocGroup:
    if DocType(row.code) == DocType.OTHER:
        if doc_group is None:
            raise UploadRefused("bad_field", "doc_group is required for doc_type other")
        try:
            group = DocGroup(str(doc_group).strip().lower())
        except ValueError as exc:
            raise UploadRefused("bad_field", f"unknown doc_group {doc_group!r}") from exc
        if group == DocGroup.COURT_RECORD:
            raise UploadRefused("bad_field", "doc_group court_record is reserved for the pipeline")
        return group
    if doc_group is not None:
        raise UploadRefused("bad_field", f"doc_group is set by doc_type {row.code}")
    return DocGroup(row.doc_group)


def _doc_date(value: date | None, today: date | None = None) -> date:
    if value is None:
        raise UploadRefused("bad_field", "doc_date is required")
    today = today or today_ist()  # the IST calendar date (decision 23 of court-data-freshness)
    if value > today:
        raise UploadRefused("bad_field", "doc_date cannot be in the future")
    if value < EARLIEST_DOC_DATE:
        raise UploadRefused("bad_field", f"doc_date cannot be before {EARLIEST_DOC_DATE.isoformat()}")
    return value


def _visibility(value: str | None) -> Visibility:
    try:
        return Visibility(str(value or "").strip().lower())
    except ValueError as exc:
        raise UploadRefused(
            "bad_field", "visibility must be case_scope, counsel_shared or private_to_office"
        ) from exc


def _reject_audit(
    session: Session, actor: Actor, case: Case | None, reason: str, filename: str, data: bytes, **extra: Any
) -> None:
    write_audit(
        session,
        actor,
        "document.upload_rejected",
        "document",
        None,
        case_id=case.id if case else None,
        after={
            "reason": reason,
            "original_filename": filename,
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            **extra,
        },
    )


# ------------------------------------------------------------------------------------------------ upload


def check_file(
    session: Session,
    actor: Actor,
    case: Case | None,
    *,
    data: bytes,
    filename: str,
    scanner: Scanner,
    max_bytes: int,
):
    """Size, type by content and the virus scan of one file, before anything is stored (decisions 3-5). A
    refused type or an infected file writes a `document.upload_rejected` audit row (`audited=True`)."""
    name = safe_filename(filename)
    if len(data) > max_bytes:
        raise UploadRefused("too_large", f"the file exceeds {max_bytes} bytes")
    try:
        ftype = detect(data, name)
    except EmptyFile as exc:
        raise UploadRefused("bad_field", "the file is empty") from exc
    except TypeNotAllowed as exc:
        _reject_audit(
            session,
            actor,
            case,
            "type_not_allowed",
            name,
            data,
            detected=exc.detected,
            extension=exc.extension,
        )
        raise UploadRefused(
            "type_not_allowed",
            "only PDF, Word (.docx without macros, .doc), JPEG and PNG files are accepted",
            audited=True,
            extra={"detected": exc.detected, "extension": exc.extension},
        ) from exc
    try:
        verdict = scanner.scan(data)
    except ScannerUnavailable as exc:
        raise UploadRefused("scanner_unavailable", f"the virus scanner gave no verdict: {exc}") from exc
    if not verdict.clean:
        _reject_audit(session, actor, case, "infected", name, data, signature=verdict.signature)
        raise UploadRefused(
            "infected",
            f"the file was refused by the virus scanner ({verdict.signature})",
            audited=True,
            extra={"signature": verdict.signature},
        )
    return ftype


inspect_file = check_file  # the name the ticket documents use (design user-memberships)


def upload(
    session: Session,
    actor: Actor,
    user: User,
    case: Case | None,
    *,
    data: bytes,
    filename: str,
    doc_type: str,
    doc_group: str | None,
    doc_date: date | None,
    description: str | None,
    visibility: str,
    scanner: Scanner,
    store: LocalStore,
    kind: DocKind = DocKind.UPLOAD,
    max_bytes: int,
    member: Member | None = None,
    allowed_types: frozenset[DocType] | None = None,
    inspected=None,
) -> Document:
    """Decisions 3–6, 9, 12. Order: fields → working relation → size → type → scan → store → row, event,
    audit. Raises `NotVisibleCase` (404) or `UploadRefused`. Kind `admin` (design `user-memberships`, decision
    20): `member` is the uploader's acting membership and `allowed_types` the ticket kind's `doc_types`."""
    if kind not in WRITE_KINDS:
        raise ValueError("upload() writes upload, attachment and admin rows only")
    if kind == DocKind.UPLOAD and case is None:
        raise UploadRefused("bad_field", "an upload needs a case")
    if kind == DocKind.ADMIN:
        if case is not None or member is None:
            raise ValueError("an admin document has no case and needs the acting membership")
        type_row = _doc_type(session, doc_type, allowed_types or frozenset())
        group = DocGroup.INTERNAL
        vis = Visibility.PRIVATE_TO_OFFICE
        text_ = (description or "").strip()[:MAX_TEXT] or type_row.label
    else:
        type_row = _doc_type(session, doc_type)
        group = _group_for(type_row, doc_group)
        text_ = _clean_text(description, "description")
        vis = _visibility(visibility)
    if kind == DocKind.ADMIN and doc_date is None:
        doc_date = today_ist()
    when = _doc_date(doc_date)
    name = safe_filename(filename)
    if case is not None:
        bases = access_basis(session, user, case)
        if not bases:
            raise NotVisibleCase("no such case")
        member = acting_member_for_case(session, user, case, Permission.DOCUMENTS_UPLOAD)
        if member is None:
            raise UploadRefused(
                "not_working_on_case",
                "your office does not own, hold or appear in this case",
                extra={"access_basis": bases},
            )
    if member is None:
        member = access.primary_member(session, user)
    office = member.office if member is not None else None
    if office is None:
        raise UploadRefused("bad_field", "the uploader has no office")
    actor = access.actor_as(actor, member)
    ftype = (
        inspected
        if inspected is not None
        else check_file(session, actor, case, data=data, filename=name, scanner=scanner, max_bytes=max_bytes)
    )
    sha = hashlib.sha256(data).hexdigest()
    if case is not None and kind == DocKind.UPLOAD:
        existing = session.scalar(
            select(Document).where(
                Document.case_id == case.id,
                Document.office_id == office.id,
                Document.sha256 == sha,
                Document.kind == DocKind.UPLOAD,
                Document.archived_at.is_(None),
            )
        )
        if existing is not None:
            raise UploadRefused(
                "duplicate",
                f"this file is already on the case as {existing.ref_no}",
                extra={"existing_ref_no": existing.ref_no},
            )
    return create_document(
        session,
        actor,
        user,
        case,
        data=data,
        mime=ftype.mime,
        filename=name,
        kind=kind,
        doc_type=DocType(type_row.code),
        doc_group=group,
        doc_date=when,
        description=text_,
        visibility=vis,
        office=office,
        store=store,
    )


def create_document(
    session: Session,
    actor: Actor,
    user: User,
    case: Case | None,
    *,
    data: bytes,
    mime: str,
    filename: str,
    kind: DocKind,
    doc_type: DocType,
    doc_group: DocGroup,
    doc_date: date,
    description: str,
    visibility: Visibility,
    office: Office,
    store: LocalStore,
) -> Document:
    """Stores a checked file (`check_file`) and writes its row, the `document_uploaded` event (case documents)
    and the `document.uploaded` audit row (design documents-uploads decisions 5, 9, 12; split out by
    custody-workflow for note attachments). `actor` is already the acting membership's snapshot."""
    ftype_mime, name, when, text_, vis, group = mime, filename, doc_date, description, visibility, doc_group
    stored = store.put(data, ftype_mime)
    now = _now()
    doc = Document(
        ref_no=allocate_ref_no(session, office.code, RecordType.DOC.value),
        sha256=stored.sha256,
        storage_key=stored.key,
        mime=ftype_mime,
        size_bytes=stored.size,
        original_filename=name,
        kind=kind,
        doc_type=doc_type,
        doc_group=group,
        case_id=case.id if case else None,
        doc_date=when,
        description=text_,
        visibility=vis,
        office_id=office.id,
        virus_scan_status=ScanStatus.CLEAN,
        scanned_at=now,
        text_status=_text_status_for(ftype_mime),
        sourcetrace_status=sourcetrace_status_for(group, vis),
        actor_user_id=user.id,
        actor_name=actor.name[:200],
        actor_designation=(actor.designation or None) and actor.designation[:200],
        actor_office_code=office.code,
    )
    session.add(doc)
    session.flush()
    if kind == DocKind.ADMIN:
        write_audit(
            session,
            actor,
            "document.uploaded",
            "document",
            doc.id,
            after={
                "ref_no": doc.ref_no,
                "kind": "admin",
                "doc_type": doc.doc_type.value,
                "original_filename": name,
                "mime": ftype_mime,
                "size_bytes": stored.size,
                "sha256": stored.sha256,
            },
        )
        session.flush()
        return doc
    payload = {
        "document_id": str(doc.id),
        "ref_no": doc.ref_no,
        "doc_type": doc.doc_type.value,
        "doc_group": group.value,
        "visibility": vis.value,
        "office_code": office.code,
    }
    emit_event(
        session,
        EventType.DOCUMENT_UPLOADED,
        case,
        payload,
        dedupe=f"document_uploaded:{doc.id}",
        scoped=True,
        actor_user_id=user.id,
    )
    write_audit(
        session,
        actor,
        "document.uploaded",
        "document",
        doc.id,
        case_id=case.id if case else None,
        after={
            "ref_no": doc.ref_no,
            "kind": DocKind(kind).value,
            "doc_type": doc.doc_type.value,
            "doc_group": group.value,
            "visibility": vis.value,
            "original_filename": name,
            "mime": ftype_mime,
            "size_bytes": stored.size,
            "sha256": stored.sha256,
            "sourcetrace_status": doc.sourcetrace_status.value,
        },
    )
    session.flush()
    return doc


# ------------------------------------------------------------------------------------------------ reading


def _order_for(session: Session, doc: Document, case: Case | None = None) -> Order | None:
    stmt = select(Order).where(Order.document_id == doc.id)
    if case is not None:
        stmt = stmt.where(Order.case_id == case.id)
    elif doc.case_id is not None:
        stmt = stmt.order_by((Order.case_id == doc.case_id).desc())
    return session.scalar(stmt.limit(1))


def can_manage(session: Session, user: User, doc: Document) -> bool:
    """Decision 13: the uploader, a department-wide caller of the uploading office's department, or the super
    admin; never on a court record."""
    if DocGroup(doc.doc_group) == DocGroup.COURT_RECORD or DocKind(doc.kind) not in USER_KINDS:
        return False
    members = access.members(session, user)
    if any(m.is_super_admin for m in members):
        return True
    uploaders = [m for m in members if m.holds(Permission.DOCUMENTS_UPLOAD)]
    if not uploaders:
        return False
    if doc.actor_user_id == user.id:
        return True
    office = session.get(Office, doc.office_id) if doc.office_id else None
    return office is not None and any(
        m.department is not None
        and visibility.whole_department(session, m)
        and visibility.in_subtree(office, m.department)
        for m in uploaders
    )


def document_out(
    session: Session,
    user: User,
    doc: Document,
    *,
    case: Case | None = None,
    order: Order | None = None,
    doc_type_label: str | None = None,
) -> dict[str, Any]:
    office = session.get(Office, doc.office_id) if doc.office_id else None
    case_row = case
    if case_row is None and doc.case_id is not None:
        case_row = session.get(Case, doc.case_id)
    if order is None:
        order = _order_for(session, doc, case)
    if case_row is None and order is not None:
        case_row = session.get(Case, order.case_id)
    if doc_type_label is None:
        ref = session.get(RefDocType, _value(doc.doc_type))
        doc_type_label = ref.label if ref else _value(doc.doc_type)
    return {
        "id": doc.id,
        "ref_no": doc.ref_no,
        "kind": _value(doc.kind),
        "doc_type": _value(doc.doc_type),
        "doc_type_label": doc_type_label,
        "doc_group": _value(doc.doc_group),
        "doc_date": doc.doc_date,
        "description": doc.description,
        "original_filename": doc.original_filename,
        "mime": doc.mime,
        "size_bytes": doc.size_bytes,
        "visibility": _value(doc.visibility),
        "office": {"code": office.code, "name": office.name} if office else None,
        "uploaded_by": (
            {
                "name": doc.actor_name,
                "designation": doc.actor_designation,
                "office_code": doc.actor_office_code,
            }
            if doc.actor_name
            else None
        ),
        "uploaded_at": doc.created_at,
        "virus_scan_status": _value(doc.virus_scan_status),
        "text_status": _value(doc.text_status),
        "page_count": doc.page_count,
        "text_extracted_at": doc.text_extracted_at,
        "sourcetrace_status": _value(doc.sourcetrace_status),
        "sourcetrace_ingested_at": (
            doc.sourcetrace_ingested_at
            if SourcetraceStatus(doc.sourcetrace_status) == SourcetraceStatus.INGESTED
            else None
        ),
        "assistant_available": SourcetraceStatus(doc.sourcetrace_status) == SourcetraceStatus.INGESTED,
        "archived_at": doc.archived_at,
        "archive_reason": doc.archive_reason,
        "order": (
            {
                "id": order.id,
                "order_no": order.order_no,
                "order_date": order.order_date,
                "kind": _value(order.kind),
            }
            if order
            else None
        ),
        "case": (
            {
                "id": case_row.id,
                "ref_no": case_row.ref_no,
                "cnr": case_row.cnr,
                "case_no_text": case_row.case_no_text,
            }
            if case_row
            else None
        ),
        "can_manage": can_manage(session, user, doc),
    }


def _case_documents_condition(case: Case):
    """Uploads of the case and the order documents of the case's orders."""
    return or_(
        (Document.case_id == case.id) & (Document.kind == DocKind.UPLOAD),
        Document.id.in_(
            select(Order.document_id).where(Order.case_id == case.id, Order.document_id.is_not(None))
        ),
    )


def _count(session: Session, stmt: Select) -> int:
    return int(session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0)


def _filters(stmt: Select, *, group: str | None, doc_type: str | None) -> Select:
    if group:
        stmt = stmt.where(Document.doc_group == DocGroup(group.strip().lower()))
    if doc_type:
        stmt = stmt.where(Document.doc_type == DocType(doc_type.strip().lower()))
    return stmt


def list_for_case(
    session: Session,
    user: User,
    case: Case,
    *,
    group: str | None = None,
    doc_type: str | None = None,
    include_archived: bool = False,
    limit: int | None = None,
    offset: int | None = None,
) -> Page:
    require_visible(session, user, case)
    stmt = select(Document).where(_case_documents_condition(case), document_visible_condition(session, user))
    if not include_archived:
        stmt = stmt.where(Document.archived_at.is_(None))
    stmt = _filters(stmt, group=group, doc_type=doc_type)
    stmt = stmt.order_by(Document.doc_date.desc().nulls_last(), Document.created_at.desc())
    limit, offset = inbox.clamp(limit, offset)
    total = _count(session, stmt)
    rows = session.scalars(stmt.limit(limit).offset(offset)).all()
    labels = {r.code: r.label for r in session.scalars(select(RefDocType)).all()}
    return Page(
        [
            document_out(session, user, d, case=case, doc_type_label=labels.get(_value(d.doc_type)))
            for d in rows
        ],
        total,
    )


def visible_count(session: Session, user: User, case: Case) -> int:
    return _count(
        session,
        select(Document.id).where(
            _case_documents_condition(case),
            document_visible_condition(session, user),
            Document.archived_at.is_(None),
        ),
    )


def resolve_document_ref(session: Session, ref: str) -> Document:
    s = (ref or "").strip()
    doc = None
    try:
        doc = session.get(Document, uuid.UUID(s))
    except ValueError:
        ref_no = ref_no_from_url(s)
        if ref_no is not None:
            doc = session.scalar(select(Document).where(Document.ref_no == ref_no))
    if doc is None:
        raise NotVisibleDocument("no such document")
    return doc


def get(session: Session, user: User, ref: str) -> Document:
    """A document by id or `ref_no`; unknown and not visible both raise `NotVisibleDocument`."""
    doc = resolve_document_ref(session, ref)
    require_visible_document(session, user, doc)
    return doc


# ------------------------------------------------------------------------------------------------ files


def _served_name(session: Session, doc: Document, order: Order | None) -> str:
    ext = EXT_FOR_MIME.get(doc.mime, "bin")
    if order is not None:
        case = session.get(Case, order.case_id)
        label = ((case.case_no_text or case.cnr) if case else None) or "order"
        base = f"{label}_{order.order_no}_{order.order_date.isoformat()}"
        return safe_filename(base.replace("/", "-").replace(" ", "") + f".{ext}")
    name = doc.original_filename or f"{(doc.ref_no or str(doc.id)).replace('/', '-')}.{ext}"
    return safe_filename(name)


def serve_stored(
    session: Session,
    doc: Document,
    disposition: str,
    *,
    store: LocalStore,
    filename: str | None = None,
) -> ServedFile:
    """The stored file of a document, after the caller has made its own checks (design `portal-causelist`,
    decision 9): inline only for PDF, JPEG and PNG; a file missing from the store records a `source_failures`
    row and raises `FileMissing`; the served name is `filename` or the document's own. Writes no audit row."""
    if disposition == "inline" and doc.mime not in INLINE_MIMES:
        raise InlineNotSupported("inline viewing is offered for PDF, JPEG and PNG only")
    path = store.path(doc.storage_key)
    if not path.is_file():
        record_failure(
            session, MISSING_FILE_KIND, str(doc.id), f"{doc.storage_key} is missing from the store"
        )
        session.flush()
        raise FileMissing(f"the stored file of {doc.ref_no or doc.id} is missing")
    if filename is None:
        order = _order_for(session, doc) if DocKind(doc.kind) == DocKind.ORDER else None
        filename = _served_name(session, doc, order)
    return ServedFile(path, doc.mime, filename, doc.size_bytes, disposition)


def open_file(
    session: Session,
    actor: Actor,
    user: User,
    doc: Document,
    *,
    store: LocalStore,
    disposition: str = "attachment",
) -> ServedFile:
    """Decision 14: `inline` needs `documents.view` (PDF and images only), `attachment` needs
    `documents.download`; the visibility rule either way; downloads of user files are audited (once the file is
    known to be there)."""
    disposition = (disposition or "attachment").strip().lower()
    if disposition not in ("inline", "attachment"):
        raise DocumentError("disposition must be inline or attachment")
    permission = Permission.DOCUMENTS_VIEW if disposition == "inline" else Permission.DOCUMENTS_DOWNLOAD
    if not access.has(session, user, permission):
        raise NotAllowed(f"{permission.value} is not enabled for you")
    require_visible_document(session, user, doc, permission=permission)
    served = serve_stored(session, doc, disposition, store=store)
    if DocKind(doc.kind) in USER_KINDS:
        write_audit(
            session,
            actor,
            "document.downloaded",
            "document",
            doc.id,
            case_id=doc.case_id,
            after={
                "ref_no": doc.ref_no,
                "disposition": disposition,
                "original_filename": doc.original_filename,
            },
        )
    return served


def order_file(
    session: Session,
    actor: Actor,
    user: User,
    case: Case,
    order_id: uuid.UUID,
    *,
    store: LocalStore,
    disposition: str = "attachment",
) -> ServedFile:
    require_visible(session, user, case)
    order = session.scalar(select(Order).where(Order.id == order_id, Order.case_id == case.id))
    if order is None:
        raise CaseNotFound("no such order")
    if order.document_id is None:
        raise OrderNotStored(_value(order.download_status))
    doc = session.get(Document, order.document_id)
    return open_file(session, actor, user, doc, store=store, disposition=disposition)


# ------------------------------------------------------------------------------------------------ changes


def _manageable(session: Session, user: User, doc: Document) -> None:
    if DocGroup(doc.doc_group) == DocGroup.COURT_RECORD or DocKind(doc.kind) not in USER_KINDS:
        raise DocumentError("court records cannot be changed")
    if not can_manage(session, user, doc):
        raise NotAllowed(
            "only the uploader, the department's head or admin, or the super admin may change this"
        )


def lock_document(session: Session, doc: Document) -> Document:
    """Design sourcetrace-connector, decision 6: the row `FOR UPDATE NOWAIT`, re-read under the lock; a row being
    sent to SourceTrace raises `DocumentBusy` (409) instead of waiting for the connector's timeout."""
    try:
        with session.begin_nested():
            locked = session.scalar(
                select(Document)
                .where(Document.id == doc.id)
                .with_for_update(nowait=True)
                .execution_options(populate_existing=True)
            )
    except OperationalError as exc:
        if getattr(getattr(exc, "orig", None), "sqlstate", None) == "55P03":  # lock_not_available
            raise DocumentBusy("the document is being sent to SourceTrace; try again in a minute") from exc
        raise
    return locked if locked is not None else doc


def change_visibility(session: Session, actor: Actor, user: User, doc: Document, new: str) -> Document:
    """Decision 13 with decision 9: the SourceTrace status follows the new visibility; an ingested court filing
    cannot be narrowed to private (409). Design sourcetrace-connector, decisions 6 and 10: the row is locked first
    (409 `document_busy` during a send); widening a private filing re-queues it with no attempts and no wait; a
    change between `case_scope` and `counsel_shared` touches nothing; an archived filing is never re-queued."""
    require_visible_document(session, user, doc)
    _not_attachment(doc)
    _manageable(session, user, doc)
    vis = _visibility(new)
    doc = lock_document(session, doc)
    old = Visibility(doc.visibility)
    if vis == old:
        return doc
    before = {"visibility": old.value, "sourcetrace_status": _value(doc.sourcetrace_status)}
    group = DocGroup(doc.doc_group)
    status = SourcetraceStatus(doc.sourcetrace_status)
    if group == DocGroup.COURT_FILING:
        if vis == Visibility.PRIVATE_TO_OFFICE:
            if status == SourcetraceStatus.INGESTED:
                raise AlreadyIngested("the document is already available to the Case Assistant")
            doc.sourcetrace_status = SourcetraceStatus.NOT_APPLICABLE
        elif old == Visibility.PRIVATE_TO_OFFICE and doc.archived_at is None:
            doc.sourcetrace_status = SourcetraceStatus.PENDING
            doc.sourcetrace_attempts = 0
            doc.sourcetrace_next_at = None
    doc.visibility = vis
    session.flush()
    write_audit(
        session,
        actor,
        "document.visibility_changed",
        "document",
        doc.id,
        case_id=doc.case_id,
        before=before,
        after={"visibility": vis.value, "sourcetrace_status": _value(doc.sourcetrace_status)},
    )
    return doc


def archive(session: Session, actor: Actor, user: User, doc: Document, reason: str | None) -> Document:
    """Design sourcetrace-connector, decisions 6 and 9: the row is locked first (409 `document_busy` during a
    send); a `pending` or `failed` document stops being sent (`not_applicable`); an `ingested` one keeps its
    reference. The status change is in the audit row's before / after."""
    require_visible_document(session, user, doc)
    _not_attachment(doc)
    _manageable(session, user, doc)
    if doc.archived_at is not None:
        raise DocumentError("the document is already archived")
    text_ = (reason or "").strip()
    if not MIN_TEXT <= len(text_) <= MAX_TEXT:
        raise DocumentError(f"reason must be {MIN_TEXT} to {MAX_TEXT} characters")
    doc = lock_document(session, doc)
    if doc.archived_at is not None:
        raise DocumentError("the document is already archived")
    before_status = _value(doc.sourcetrace_status)
    if SourcetraceStatus(doc.sourcetrace_status) in (SourcetraceStatus.PENDING, SourcetraceStatus.FAILED):
        doc.sourcetrace_status = SourcetraceStatus.NOT_APPLICABLE
        doc.sourcetrace_next_at = None
    doc.archived_at = _now()
    doc.archive_reason = text_
    session.flush()
    write_audit(
        session,
        actor,
        "document.archived",
        "document",
        doc.id,
        case_id=doc.case_id,
        before={"sourcetrace_status": before_status},
        after={"ref_no": doc.ref_no, "reason": text_, "sourcetrace_status": _value(doc.sourcetrace_status)},
    )
    return doc


# ------------------------------------------------------------------------------------------------ types, search


def upload_types(session: Session) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(RefDocType)
        .where(RefDocType.is_active.is_(True))
        .order_by(RefDocType.sort_order, RefDocType.code)
    ).all()
    return [
        {
            "code": r.code,
            "label": r.label,
            "doc_group": r.doc_group,
            "group_choosable": DocType(r.code) == DocType.OTHER,
        }
        for r in rows
        if DocType(r.code) not in SYSTEM_TYPES and DocType(r.code) not in ADMIN_TYPES
    ]


def search(
    session: Session,
    user: User,
    *,
    q: str,
    case: str | None = None,
    group: str | None = None,
    doc_type: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> Page:
    """Decision 15: word search over `document_text.search_vector`, restricted by the visibility rule, ranked by
    `ts_rank` then `doc_date`; the snippet is computed for the returned page only."""
    q = (q or "").strip()
    if len(q) < MIN_QUERY:
        raise DocumentError(f"q must be at least {MIN_QUERY} characters")
    query = func.websearch_to_tsquery("english", q)
    rank = func.ts_rank(DocumentText.search_vector, query).label("rank")
    stmt = (
        select(Document, rank)
        .join(DocumentText, DocumentText.document_id == Document.id)
        .where(
            DocumentText.search_vector.op("@@")(query),
            document_visible_condition(session, user),
            Document.archived_at.is_(None),
        )
    )
    if case:
        try:
            case_row = resolve_case_ref(session, case)
        except CaseNotFound:
            return Page([], 0)
        stmt = stmt.where(_case_documents_condition(case_row))
    stmt = _filters(stmt, group=group, doc_type=doc_type)
    if date_from:
        stmt = stmt.where(Document.doc_date >= date_from)
    if date_to:
        stmt = stmt.where(Document.doc_date <= date_to)
    limit = MAX_SEARCH_LIMIT if limit is None else max(1, min(int(limit), MAX_SEARCH_LIMIT))
    offset = max(0, int(offset or 0))
    total = _count(session, stmt)
    rows = session.execute(
        stmt.order_by(rank.desc(), Document.doc_date.desc().nulls_last(), Document.id)
        .limit(limit)
        .offset(offset)
    ).all()
    docs = [d for d, _ in rows]
    snippets: dict[uuid.UUID, str] = {}
    if docs:
        for doc_id, snippet in session.execute(
            select(
                DocumentText.document_id,
                func.ts_headline(
                    "english",
                    func.left(DocumentText.full_text, 200_000),
                    query,
                    text("'MaxWords=40, MinWords=15, MaxFragments=2, StartSel=[[, StopSel=]]'"),
                ),
            ).where(DocumentText.document_id.in_([d.id for d in docs]))
        ).all():
            snippets[doc_id] = snippet
    case_ids = {d.case_id for d in docs if d.case_id}
    cases = session.scalars(select(Case).where(Case.id.in_(case_ids))).all() if case_ids else []
    summaries = inbox.summaries(session, list(cases))
    items = []
    for doc, score in rows:
        items.append(
            {
                "document": document_out(session, user, doc),
                "case": summaries.get(doc.case_id),
                "snippet": snippets.get(doc.id),
                "rank": float(score or 0),
            }
        )
    return Page(items, total)
