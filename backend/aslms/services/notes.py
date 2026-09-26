"""The case notes trail (plan §5.8; decisions log). Append-only (database triggers refuse UPDATE/DELETE);
corrections are new notes that supersede the old one, both kept. Author snapshot frozen; per-case sequence
number; the custody leg the note was written in is recorded. Attachments go on the documents substrate
(virus-scanned, deduplicated) and are always internal documents: never sent to SourceTrace.

Visibility, on top of the case scope:
  case_scope         everyone in the case scope except standing counsel
  counsel_shared     everyone in the case scope, including standing counsel
  private_to_office  the author's office (and offices below it), and the State tier"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement

from aslms.core.errors import NotFoundError, ValidationError
from aslms.domain.cases import Case
from aslms.domain.documents import DocType, Document, Visibility
from aslms.domain.events import EventType
from aslms.domain.org import Office, Role
from aslms.domain.workflow import CaseNote, CaseNoteAttachment, Custody, NoteKind, NoteVisibility
from aslms.services import audit, documents, events
from aslms.services.audit import Actor
from aslms.services.scope import Principal

MAX_NOTE_CHARS = 20_000


@dataclass
class NoteIn:
    kind: NoteKind
    body: str
    visibility: NoteVisibility = NoteVisibility.CASE_SCOPE
    supersedes_id: uuid.UUID | None = None
    attachments: list[documents.UploadRequest] = field(default_factory=list)
    source: str | None = None


def add_note(session: Session, actor: Actor, p: Principal, case: Case, note: NoteIn) -> CaseNote:
    if p.read_only:
        raise ValidationError("your role is read-only")
    body = (note.body or "").strip()
    if not body:
        raise ValidationError("a note cannot be empty")
    if len(body) > MAX_NOTE_CHARS:
        raise ValidationError(
            f"a note is limited to {MAX_NOTE_CHARS} characters; attach longer text as a file"
        )
    if note.kind == NoteKind.SYSTEM:
        raise ValidationError("system notes are written by the portal only")
    if note.supersedes_id:
        old = session.get(CaseNote, note.supersedes_id)
        if old is None or old.case_id != case.id:
            raise NotFoundError("the note being corrected is not in this case")
    session.execute(select(func.pg_advisory_xact_lock(func.hashtext(f"notes:{case.id}"))))
    seq = (session.scalar(select(func.max(CaseNote.seq_no)).where(CaseNote.case_id == case.id)) or 0) + 1
    cur = session.get(Custody, case.id)
    n = CaseNote(
        case_id=case.id,
        seq_no=seq,
        kind=note.kind,
        body=body,
        visibility=note.visibility,
        office_id=p.office_id,
        author_role=p.role.value,
        custody_leg_id=cur.current_leg_id if cur else None,
        supersedes_id=note.supersedes_id,
        source=note.source,
        **actor.snapshot(),
    )
    session.add(n)
    session.flush()
    attached: set[uuid.UUID] = set()
    for req in note.attachments:
        req = documents.UploadRequest(
            req.filename,
            req.content,
            req.doc_type if req.doc_type in documents.UPLOADABLE_TYPES else DocType.OTHER,
            req.doc_date,
            req.description or f"Attachment to note {seq}",
            Visibility(note.visibility.value),
            internal=True,
        )
        doc = _attach(session, actor, p, case, req)
        if doc.id in attached:
            continue  # the same file given twice is stored and linked once (sha256 dedupe)
        attached.add(doc.id)
        session.add(CaseNoteAttachment(note_id=n.id, document_id=doc.id))
        events.emit(
            session,
            EventType.FILE_ADDED,
            f"note_file:{n.id}:{doc.id}",
            case_id=case.id,
            actor_user_id=actor.user_id,
            payload={"note_seq": seq, "document_id": str(doc.id), "filename": req.filename},
        )
    events.emit(
        session,
        EventType.NOTE_ADDED,
        f"note:{n.id}",
        case_id=case.id,
        actor_user_id=actor.user_id,
        payload={
            "seq_no": seq,
            "kind": note.kind.value,
            "visibility": note.visibility.value,
            "supersedes": str(note.supersedes_id) if note.supersedes_id else None,
        },
    )
    audit.record(
        session,
        actor,
        "note.add",
        "case_note",
        n.id,
        case_id=case.id,
        after={"seq_no": seq, "kind": note.kind.value, "attachments": len(note.attachments)},
    )
    return n


def _attach(
    session: Session, actor: Actor, p: Principal, case: Case, req: documents.UploadRequest
) -> Document:
    """Reuses an identical file already stored for this case; otherwise uploads it (validated and scanned)."""
    sha = documents.storage.sha256_bytes(req.content)
    existing = session.scalar(select(Document).where(Document.sha256 == sha))
    if existing and existing.case_id == case.id:
        return existing
    return documents.upload(session, actor, p, case, req)


def note_visibility_clause(p: Principal) -> ColumnElement[bool]:
    if p.is_state_tier:
        return CaseNote.id.isnot(None)
    my_offices = select(Office.id).where(
        or_(Office.path == p.office_path, Office.path.like(p.office_path + "/%"))
    )
    private_ok = and_(
        CaseNote.visibility == NoteVisibility.PRIVATE_TO_OFFICE, CaseNote.office_id.in_(my_offices)
    )
    if p.role == Role.STANDING_COUNSEL:
        return or_(CaseNote.visibility == NoteVisibility.COUNSEL_SHARED, private_ok)
    return or_(
        CaseNote.visibility.in_([NoteVisibility.CASE_SCOPE, NoteVisibility.COUNSEL_SHARED]), private_ok
    )


def list_notes(
    session: Session, p: Principal, case_id: uuid.UUID
) -> list[tuple[CaseNote, list[Document], list[int]]]:
    """Notes in order with their attachments and the seq_nos of notes that supersede each one."""
    notes = list(
        session.scalars(
            select(CaseNote)
            .where(CaseNote.case_id == case_id, note_visibility_clause(p))
            .order_by(CaseNote.seq_no)
        )
    )
    ids = [n.id for n in notes]
    atts: dict[uuid.UUID, list[Document]] = {}
    if ids:
        for a, d in session.execute(
            select(CaseNoteAttachment, Document)
            .join(Document, Document.id == CaseNoteAttachment.document_id)
            .where(CaseNoteAttachment.note_id.in_(ids))
        ):
            atts.setdefault(a.note_id, []).append(d)
    superseded_by: dict[uuid.UUID, list[int]] = {}
    for n in notes:
        if n.supersedes_id:
            superseded_by.setdefault(n.supersedes_id, []).append(n.seq_no)
    return [(n, atts.get(n.id, []), superseded_by.get(n.id, [])) for n in notes]
