"""Attachments of permanent notes (design `custody-workflow`, decisions 12 and 18).

- `prepare`: every new file is size-checked, typed by content and virus-scanned *before anything is written*;
  one refused file refuses the whole call (its `document.upload_rejected` audit row is the only write, and the
  router commits it, as for uploads). At most `ATTACHMENTS_MAX_FILES` files per call; doc types come from the
  internal group (default `correspondence`).
- `resolve_links`: existing documents of the same case (directly or through one of its orders) that the caller
  can see and that are not archived; anything else is 400 `bad_document_ref`. A link never widens: a linked
  document keeps its own visibility. Drafts take links only.
- `create_all`: the prepared files become `documents` rows of kind `attachment`, group `internal` (so never sent
  to SourceTrace, `ck_documents_internal_not_sent`), dated today, with the note's visibility. Their ids are kept
  on the session so the router can dispatch text extraction after the commit (`take_new_document_ids`)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from aslms.domain.cases import Case
from aslms.domain.documents import DocGroup, DocKind, Document, Order, Visibility
from aslms.domain.org import Office, User
from aslms.domain.reference import DocType, RefDocType
from aslms.services import documents
from aslms.services.access import Member
from aslms.services.audit import Actor
from aslms.services.documents import UploadRefused
from aslms.services.filetypes import safe_filename
from aslms.services.scanner import Scanner
from aslms.services.storage import LocalStore
from aslms.services.visibility import NotVisibleDocument, can_view_document
from aslms.services.workflow_common import bad, today_ist

DEFAULT_DOC_TYPE = DocType.CORRESPONDENCE
NEW_DOCUMENTS_KEY = "aslms_new_documents"


@dataclass(frozen=True)
class Prepared:
    data: bytes
    filename: str
    mime: str
    doc_type: DocType


def internal_doc_type(session: Session, code: str | None) -> DocType:
    """A doc type of the internal group (or `other`, which an attachment files as internal); never an admin
    ticket's type."""
    raw = (code or "").strip().lower()
    if not raw:
        return DEFAULT_DOC_TYPE
    try:
        member = DocType(raw)
    except ValueError as exc:
        raise UploadRefused("bad_field", f"unknown doc_type {code!r}") from exc
    row = session.get(RefDocType, member.value)
    if (
        row is None
        or not row.is_active
        or member in documents.ADMIN_TYPES
        or (row.doc_group != DocGroup.INTERNAL.value and member != DocType.OTHER)
    ):
        raise UploadRefused("bad_field", f"doc_type {member.value} is not an internal document type")
    return member


def prepare(
    session: Session,
    actor: Actor,
    case: Case,
    files: Sequence[tuple[bytes, str]],
    doc_types: Sequence[str | None] = (),
    *,
    scanner: Scanner | None,
    max_files: int,
    max_bytes: int,
) -> list[Prepared]:
    if not files:
        return []
    if len(files) > max_files:
        raise UploadRefused("bad_field", f"at most {max_files} files may be attached at once")
    if len(doc_types) > len(files):
        raise UploadRefused("bad_field", "more file_doc_types than files")
    if scanner is None:
        raise UploadRefused("scanner_unavailable", "no virus scanner is configured")
    types = [
        internal_doc_type(session, doc_types[i] if i < len(doc_types) else None) for i in range(len(files))
    ]
    out: list[Prepared] = []
    for (data, name), doc_type in zip(files, types, strict=True):
        clean = safe_filename(name)
        ftype = documents.check_file(
            session, actor, case, data=data, filename=clean, scanner=scanner, max_bytes=max_bytes
        )
        out.append(Prepared(data, clean, ftype.mime, doc_type))
    return out


def _ref_list(refs: Sequence[str]) -> list[str]:
    out: list[str] = []
    for r in refs:
        for part in str(r or "").split(","):
            part = part.strip()
            if part and part not in out:
                out.append(part)
    return out


def resolve_links(
    session: Session, user: User | Member, case: Case, refs: Sequence[str], *, max_links: int
) -> list[Document]:
    wanted = _ref_list(refs)
    if len(wanted) > max_links:
        raise bad(f"at most {max_links} documents may be linked at once", "bad_document_ref")
    docs: list[Document] = []
    for ref in wanted:
        try:
            doc = documents.resolve_document_ref(session, ref)
        except NotVisibleDocument as exc:
            raise bad(f"no such document {ref!r}", "bad_document_ref") from exc
        same_case = doc.case_id == case.id or bool(
            session.scalar(
                select(Order.id).where(Order.document_id == doc.id, Order.case_id == case.id).limit(1)
            )
        )
        if not same_case or doc.archived_at is not None or not can_view_document(session, user, doc):
            raise bad(f"{ref} is not a document of this case that you can open", "bad_document_ref")
        if doc.id not in {d.id for d in docs}:
            docs.append(doc)
    return docs


def create_all(
    session: Session,
    actor: Actor,
    user: User | Member,
    case: Case,
    prepared: Sequence[Prepared],
    *,
    visibility: Visibility,
    description: str,
    office: Office,
    store: LocalStore | None,
) -> list[Document]:
    """`actor` is the acting membership's snapshot; `office` the note's office (what `private_to_office` reads
    by)."""
    if not prepared:
        return []
    if store is None:
        raise ValueError("a store is required to keep attachments")
    out = []
    for p in prepared:
        doc = documents.create_document(
            session,
            actor,
            user.user if isinstance(user, Member) else user,
            case,
            data=p.data,
            mime=p.mime,
            filename=p.filename,
            kind=DocKind.ATTACHMENT,
            doc_type=p.doc_type,
            doc_group=DocGroup.INTERNAL,
            doc_date=today_ist(),
            description=description[:500],
            visibility=visibility,
            office=office,
            store=store,
        )
        out.append(doc)
        session.info.setdefault(NEW_DOCUMENTS_KEY, []).append(doc.id)
    return out


def take_new_document_ids(session: Session) -> list[uuid.UUID]:
    """The ids of the attachment documents written in this session (cleared on read)."""
    return list(session.info.pop(NEW_DOCUMENTS_KEY, []))
