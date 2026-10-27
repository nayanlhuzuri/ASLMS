"""The internal records of one case for the local model (design `assistant-ollama`, decisions 4 to 6 and 9): pure
gathering under the case page's own rules. Imports neither a connector nor `integration.ollama`, and no write service.

Read only for a question in a case-tab conversation switched on with "Include This Case's Internal Records" (the
service decides that from the stored conversation, never from the client), only for that conversation's case, and only
what the asker may open on the case page at that moment:
- the asker can see the case (`visibility.can_view_case`) and holds the case page's read guard (`cases.view_scope` or
  `cases.view_all`); otherwise nothing at all;
- saved notes under `visibility.note_visible_condition` (per-note visibility, private-to-office, counsel-shared, the
  tiers, `cases.view_private_all`); unsent drafts are never read, not even the asker's own (this module never names
  the draft tables);
- the file movement through `custody.history` (newest first, at most 30 legs), remarks only when
  `custody.shows_remark` is true, as on the custody tab;
- department documents (uploads in group `internal`, and note attachments of notes the asker may read) under
  `visibility.document_visible_condition`, clean, not archived, with extracted text; their pages are ranked by the
  connector inside its own time budget (`assistant_preview.page_matches`).

Everything visible is supplied whole, in a fixed order, within `ASSISTANT_OLLAMA_INTERNAL_CHARS` (decision 6); the
texts live in memory for one call only. Stored citations hold references (`note_id` and the character range, the leg
range and whether remarks were included, the document and page) and `render` re-renders the text at read time under
the reader's current rules; `recheck` decides whether the reader may still see each record (decision 9)."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import and_, exists, func, literal, select
from sqlalchemy.orm import Session

from aslms.domain.assistant import AssistantConversation
from aslms.domain.cases import Case
from aslms.domain.documents import DocGroup, DocKind, Document, DocumentText, ScanStatus
from aslms.domain.org import User
from aslms.domain.reference import Permission, RefDocType, RefNoteKind
from aslms.domain.workflow import CaseNote, CaseNoteAttachment, CustodyHistory
from aslms.services import access, custody, visibility

MAX_LEGS = 30
REMARK_CHARS = 500
NOTE_CHARS = 3000
PAGE_CHARS = 3000
DOC_PAGES = 3
DOC_CANDIDATES = 50
# decision 4: the deterministic keyword check offering the switch (no model call; a suggestion only)
SUGGEST_WORDS = (
    "we decided",
    "our note",
    "note",
    "noting",
    "who has the file",
    "file is with",
    "with whom",
    "pending",
    "pending action",
    "due date",
    "remark",
    "sent to",
    "returned",
    "internal",
    "department document",
    "our reply",
    "our stand",
)
_SUGGEST_RE = [re.compile(r"\b" + re.escape(w) + r"(?:s|es|d|ed)?\b") for w in SUGGEST_WORDS]
_WORD_RE = re.compile(r"[a-z0-9]{3,}")
STOP = frozenset(
    "the and for with what was were has have had did does this that from our are who whom which when where why how "
    "any all not but can will shall may into about case".split()
)


@dataclass(frozen=True)
class MovementSource:
    """One source, "File Movement (Internal)": the legs newest first, one line each."""

    case_id: uuid.UUID
    text: str
    legs: tuple[int, int]  # [first, last] seq_no shown (newest first: first >= last)
    remarks: bool
    count: int


@dataclass(frozen=True)
class NoteSource:
    note_id: uuid.UUID
    seq_no: int
    header: str
    text: str
    chars: tuple[int, int]
    corrected: bool  # a visible correction of it exists
    matched: bool
    visibility: str


@dataclass(frozen=True)
class DocumentRef:
    """A visible department document or note attachment with extracted text; its pages are ranked later."""

    document_id: uuid.UUID
    kind: str  # department_document | note_attachment
    label: str


@dataclass(frozen=True)
class InternalRecords:
    case_id: uuid.UUID
    file_movement: MovementSource | None = None
    notes: tuple[NoteSource, ...] = ()
    documents: tuple[DocumentRef, ...] = ()
    doc_chars: int = 0  # what is left of the budget for document pages
    counts: dict[str, int] = field(default_factory=dict)
    dropped: dict[str, int] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return self.file_movement is None and not self.notes and not self.documents


def read_guard(session: Session, user: User) -> bool:
    """The case page's guard on the notes, custody, hearings and listings routes (decision 5)."""
    return access.has(session, user, Permission.CASES_VIEW_SCOPE) or access.has(
        session, user, Permission.CASES_VIEW_ALL
    )


def _allowed(session: Session, user: User, case: Case) -> bool:
    return read_guard(session, user) and visibility.can_view_case(session, user, case)


def _words(question: str) -> set[str]:
    return {w for w in _WORD_RE.findall((question or "").lower()) if w not in STOP}


def suggests(question: str) -> bool:
    """Decision 4: one of `SUGGEST_WORDS` in the question (word-bounded, case-insensitive)."""
    q = (question or "").lower()
    return any(r.search(q) for r in _SUGGEST_RE)


def _v(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def _date(value: Any) -> str:
    return value.strftime("%d %b %Y") if value is not None else "-"


# ------------------------------------------------------------------------------------------------ the file movement


def _leg_line(leg: dict[str, Any], show_remark: bool) -> str:
    office = (
        (leg.get("holder_office") or {}).get("name") or (leg.get("holder_office") or {}).get("code") or "-"
    )
    to = ", ".join(p for p in (leg.get("holder_designation"), office) if p)
    frm = ", ".join(p for p in (leg.get("actor_designation"), leg.get("actor_office_code")) if p) or "-"
    parts = [
        f"{_date(leg.get('started_at'))}: from {frm} to {to}",
        f"reason: {leg.get('reason_label') or leg.get('reason') or '-'}",
        f"pending action: {leg.get('pending_action_label') or '-'}",
        f"due date: {_date(leg.get('due_date'))}",
    ]
    remark = leg.get("remark")
    if show_remark and remark:
        parts.append(f"remark: {remark[:REMARK_CHARS]}")
    return "; ".join(parts)


def _movement(session: Session, user: User, case: Case) -> MovementSource | None:
    out = custody.history(session, user, case, limit=MAX_LEGS, order="desc")
    legs = out["legs"]
    if not legs:
        return None
    shown = bool(out["remarks_shown"])
    lines = [_leg_line(leg, shown) for leg in legs]
    return MovementSource(
        case_id=case.id,
        text="\n".join(lines),
        legs=(int(legs[0]["seq_no"]), int(legs[-1]["seq_no"])),
        remarks=shown,
        count=len(legs),
    )


def _movement_render(session: Session, user: User, case: Case, legs: list[int], remarks: bool) -> str | None:
    first, last = (int(legs[0]), int(legs[1])) if len(legs) == 2 else (None, None)
    if first is None:
        return None
    hi, lo = max(first, last), min(first, last)
    rows = session.scalars(
        select(CustodyHistory)
        .where(CustodyHistory.case_id == case.id, CustodyHistory.seq_no.between(lo, hi))
        .order_by(CustodyHistory.seq_no.desc())
    ).all()
    show = remarks and custody.shows_remark(session, user, case)
    return "\n".join(_leg_line(custody.leg_out(session, r, show_remark=show), show) for r in rows) or None


# ------------------------------------------------------------------------------------------------ notes


def _kind_labels(session: Session) -> dict[str, str]:
    return {r.code: r.label for r in session.scalars(select(RefNoteKind)).all()}


def _visible_notes(session: Session, user: User, case: Case) -> list[CaseNote]:
    return list(
        session.scalars(
            select(CaseNote)
            .where(CaseNote.case_id == case.id, visibility.note_visible_condition(session, user))
            .order_by(CaseNote.seq_no.desc())
        ).all()
    )


def _note_header(
    note: CaseNote, labels: dict[str, str], *, corrected_by: int | None, corrects: int | None
) -> str:
    kind = labels.get(_v(note.kind), _v(note.kind))
    by = ", ".join(p for p in (note.actor_designation, note.actor_office_code) if p) or "-"
    head = f"Note {note.seq_no}, {kind}, {_date(note.created_at)}, by {by}"
    if corrected_by is not None:
        head += f"; Corrected by Note {corrected_by}"
    if corrects is not None:
        head += f"; Corrects Note {corrects}"
    return head


def _notes(session: Session, user: User, case: Case, question: str) -> list[NoteSource]:
    rows = _visible_notes(session, user, case)
    if not rows:
        return []
    labels = _kind_labels(session)
    seq = {n.id: n.seq_no for n in rows}
    corrected_by = {n.supersedes_id: n.seq_no for n in rows if n.supersedes_id in seq}
    words = _words(question)
    matched = {n.id for n in rows if words and words & set(_WORD_RE.findall(n.body.lower()))}
    # a correction and the note it corrects share their group
    group = set(matched)
    for n in rows:
        if n.supersedes_id in seq and (n.id in matched or n.supersedes_id in matched):
            group |= {n.id, n.supersedes_id}
    ordered = sorted(rows, key=lambda n: (n.id not in group, -n.seq_no))
    out = []
    for n in ordered:
        body = n.body[:NOTE_CHARS]
        out.append(
            NoteSource(
                note_id=n.id,
                seq_no=n.seq_no,
                header=_note_header(
                    n,
                    labels,
                    corrected_by=corrected_by.get(n.id),
                    corrects=seq.get(n.supersedes_id) if n.supersedes_id else None,
                ),
                text=body,
                chars=(0, len(body)),
                corrected=n.id in corrected_by,
                matched=n.id in group,
                visibility=_v(n.visibility),
            )
        )
    return out


# ------------------------------------------------------------------------------------------------ documents


def _department_documents_condition(session: Session, user: User, case: Case):
    """Uploads of group `internal` of the case, and note attachments of the case's notes that the asker may read;
    each visible to the asker under the ordinary document rule, clean, not archived, with extracted text."""
    attached = exists(
        select(literal(1))
        .select_from(CaseNoteAttachment)
        .join(CaseNote, CaseNote.id == CaseNoteAttachment.note_id)
        .where(
            CaseNoteAttachment.document_id == Document.id,
            CaseNote.case_id == case.id,
            visibility.note_visible_condition(session, user),
        )
    )
    internal = and_(
        Document.case_id == case.id, Document.kind == DocKind.UPLOAD, Document.doc_group == DocGroup.INTERNAL
    )
    has_text = exists(
        select(literal(1))
        .select_from(DocumentText)
        .where(DocumentText.document_id == Document.id, DocumentText.full_text.is_not(None))
    )
    return and_(
        internal | and_(Document.kind == DocKind.ATTACHMENT, attached),
        visibility.document_visible_condition(session, user),
        Document.archived_at.is_(None),
        Document.virus_scan_status == ScanStatus.CLEAN,
        has_text,
    )


def _documents(session: Session, user: User, case: Case) -> list[DocumentRef]:
    labels = {r.code: r.label for r in session.scalars(select(RefDocType)).all()}
    rows = session.scalars(
        select(Document)
        .where(_department_documents_condition(session, user, case))
        .order_by(Document.doc_date.desc().nulls_last(), Document.created_at.desc(), Document.id)
        .limit(DOC_CANDIDATES)
    ).all()
    return [
        DocumentRef(
            document_id=d.id,
            kind="note_attachment" if DocKind(d.kind) == DocKind.ATTACHMENT else "department_document",
            label=labels.get(_v(d.doc_type), _v(d.doc_type)) or "Document",
        )
        for d in rows
    ]


# ------------------------------------------------------------------------------------------------ gathering


def gather(session: Session, user: User, case: Case, question: str, *, budget_chars: int) -> InternalRecords:
    """Decisions 5 and 6, in transaction A: the file movement first (never dropped), then the notes in their fixed
    order while the budget lasts (notes already corrected dropped first, then the oldest), then the department
    documents (their pages get what is left). An asker without case sight or the read guard, or a budget of 0, gets
    an empty set."""
    empty = InternalRecords(case_id=case.id)
    if budget_chars <= 0 or not _allowed(session, user, case):
        return empty
    movement = _movement(session, user, case)
    used = len(movement.text) if movement else 0
    notes = _notes(session, user, case, question)
    keep = list(notes)
    dropped_notes = 0

    def size(items: list[NoteSource]) -> int:
        return sum(len(n.header) + len(n.text) + 2 for n in items)

    while keep and used + size(keep) > budget_chars:
        victim = next((n for n in reversed(keep) if n.corrected), None)
        if victim is None:
            victim = min(keep, key=lambda n: n.seq_no)  # the oldest
        keep.remove(victim)
        dropped_notes += 1
    used += size(keep)
    documents = _documents(session, user, case)
    return InternalRecords(
        case_id=case.id,
        file_movement=movement,
        notes=tuple(keep),
        documents=tuple(documents),
        doc_chars=max(0, budget_chars - used),
        counts={
            "file_movement": 1 if movement else 0,
            "note": len(keep),
            "department_document": len(documents),
        },
        dropped={"note": dropped_notes},
    )


def visible_count(session: Session, user: User, case: Case) -> int:
    """The same set as `gather`, counted with no text read: for the switch's precondition and the suggestion."""
    if not _allowed(session, user, case):
        return 0
    legs = int(
        session.scalar(
            select(func.count()).select_from(CustodyHistory).where(CustodyHistory.case_id == case.id)
        )
        or 0
    )
    notes = int(
        session.scalar(
            select(func.count())
            .select_from(CaseNote)
            .where(CaseNote.case_id == case.id, visibility.note_visible_condition(session, user))
        )
        or 0
    )
    docs = int(
        session.scalar(
            select(func.count())
            .select_from(Document)
            .where(_department_documents_condition(session, user, case))
        )
        or 0
    )
    return (1 if legs else 0) + notes + docs


# ------------------------------------------------------------------------------------------------ reading again

INTERNAL_KINDS = ("note", "file_movement", "department_document")


def _uuid(v: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(v)) if v else None
    except ValueError:
        return None


def recheck(
    session: Session, user: User, conversation: AssistantConversation, citation: dict[str, Any]
) -> bool:
    """Decision 9: may the reader still see this internal record of the conversation's case, under their current
    rules (case sight and the read guard always; a note by `note_visible_condition`; the file movement by
    `shows_remark` when remarks were included; a document by `document_visible_condition`, not archived)?"""
    kind = citation.get("source_kind")
    case_id = conversation.case_id
    if case_id is None or kind not in INTERNAL_KINDS:
        return False
    case = session.get(Case, case_id)
    if case is None or not _allowed(session, user, case):
        return False
    if kind == "note":
        note = session.get(CaseNote, _uuid(citation.get("note_id")))
        return note is not None and note.case_id == case_id and visibility.can_view_note(session, user, note)
    if kind == "file_movement":
        if _uuid(citation.get("case_id")) != case_id:
            return False
        return not citation.get("remarks") or custody.shows_remark(session, user, case)
    doc_id = _uuid(citation.get("document_id"))
    if doc_id is None:
        return False
    return bool(
        session.scalar(
            select(func.count())
            .select_from(Document)
            .where(Document.id == doc_id, _department_documents_condition(session, user, case))
        )
    )


def corrected_later(session: Session, user: User, note_id: uuid.UUID) -> int | None:
    """The `seq_no` of a visible correction of the note, if any (decision 9)."""
    return session.scalar(
        select(CaseNote.seq_no).where(
            CaseNote.supersedes_id == note_id, visibility.note_visible_condition(session, user)
        )
    )


def _page_text(session: Session, document_id: uuid.UUID, page: int | None) -> str | None:
    full = session.scalar(select(DocumentText.full_text).where(DocumentText.document_id == document_id))
    if not full:
        return None
    pages = full.split("\f")
    idx = (page or 1) - 1
    if idx < 0 or idx >= len(pages):
        return None
    return pages[idx].strip()[:PAGE_CHARS]


def render(
    session: Session, user: User, conversation: AssistantConversation, citation: dict[str, Any]
) -> str | None:
    """Decision 9: "Text Given to the Model" for an internal citation, re-rendered from the record under the reader's
    current rules (None when the reader may no longer see it). Notes, custody legs and stored document text are
    append-only or immutable, so the text is the one the model read."""
    if not recheck(session, user, conversation, citation):
        return None
    kind = citation.get("source_kind")
    case = session.get(Case, conversation.case_id)
    if kind == "note":
        note = session.get(CaseNote, _uuid(citation.get("note_id")))
        start, end = (citation.get("chars") or [0, NOTE_CHARS])[:2]
        labels = _kind_labels(session)
        corrects = None
        if note.supersedes_id:
            corrects = session.scalar(select(CaseNote.seq_no).where(CaseNote.id == note.supersedes_id))
        head = _note_header(
            note, labels, corrected_by=corrected_later(session, user, note.id), corrects=corrects
        )
        return f"{head}\n{note.body[int(start) : int(end)]}"
    if kind == "file_movement":
        return _movement_render(
            session, user, case, list(citation.get("legs") or []), bool(citation.get("remarks"))
        )
    return _page_text(session, _uuid(citation.get("document_id")), citation.get("page"))
