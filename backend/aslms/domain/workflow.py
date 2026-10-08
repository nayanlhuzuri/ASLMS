"""Phase 2 — custody and workflow, the noting trail, SourceTrace ingestion records.

Design `custody-workflow` (migration 0009): the holder of a file is a membership (office + officer +
designation); sending the file and the owning department's recall replace requests (the `requests` tables are
dropped); the current holder's notes are drafts (`case_note_drafts`) made permanent when the file moves."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from aslms.db.base import (
    ActorSnapshotMixin,
    Base,
    CreatedAtMixin,
    RefNoMixin,
    TableClass,
    TimestampMixin,
    pg_enum,
    ref_code,
    uuid_fk,
    uuid_pk,
)
from aslms.domain.documents import Visibility
from aslms.domain.reference import NoteKind, Stage


class PendingAction(enum.StrEnum):
    """What the current holder is to do (design `custody-workflow`, decision 10). `none` only on ownership
    legs; a send carries any other member."""

    NONE = "none"
    EXAMINE = "examine"
    REPLY = "reply"
    FILE = "file"
    COMPLY = "comply"
    REVIEW = "review"
    PARAWISE_COMMENTS = "parawise_comments"
    REPORT = "report"
    DOCUMENTS = "documents"
    OPINION = "opinion"
    INSTRUCTIONS = "instructions"
    CLARIFICATION = "clarification"
    OTHER = "other"


PENDING_ACTION_LABELS: dict[PendingAction, str] = {
    PendingAction.NONE: "No action pending",
    PendingAction.EXAMINE: "Examine",
    PendingAction.REPLY: "Reply",
    PendingAction.FILE: "File in court",
    PendingAction.COMPLY: "Comply",
    PendingAction.REVIEW: "Review",
    PendingAction.PARAWISE_COMMENTS: "Parawise comments",
    PendingAction.REPORT: "Report",
    PendingAction.DOCUMENTS: "Furnish documents",
    PendingAction.OPINION: "Opinion",
    PendingAction.INSTRUCTIONS: "Instructions to counsel",
    PendingAction.CLARIFICATION: "Clarification",
    PendingAction.OTHER: "Other - see remark",
}

# decisions 2 and 27: the one list of custody reasons (the CHECK and `services/custody.REASONS`)
CUSTODY_REASONS = (
    "claimed",
    "allotted",
    "taken_over",
    "transferred",
    "sent",
    "recalled",
    "reassigned_on_exit",
)
CUSTODY_REASON_LABELS = {
    "claimed": "Claimed",
    "allotted": "Allotted",
    "taken_over": "Taken over",
    "transferred": "Transferred",
    "sent": "Sent",
    "recalled": "Recalled",
    "reassigned_on_exit": "Reassigned on an officer's exit",
}
# legs that carry the sender's remark (CHECK `ck_custody_history_remark`)
REMARK_REASONS = ("sent", "recalled", "reassigned_on_exit")


def _in(values: tuple[str, ...]) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


class Custody(TimestampMixin, Base):
    """Where the case is now (1:1 with the case). The holder is a membership, or an office alone after an
    ownership leg (decision 2)."""

    __tablename__ = "custody"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (Index("ix_custody_due", "due_date", postgresql_where=text("due_date IS NOT NULL")),)
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="RESTRICT"), primary_key=True
    )
    holder_office_id: Mapped[uuid.UUID] = uuid_fk("offices.id")
    holder_user_id: Mapped[uuid.UUID | None] = uuid_fk("users.id", nullable=True, ondelete="SET NULL")
    holder_membership_id: Mapped[uuid.UUID | None] = uuid_fk("user_memberships.id", nullable=True)
    pending_action: Mapped[PendingAction] = mapped_column(
        pg_enum(PendingAction, "pending_action"), nullable=False, server_default="none"
    )
    since: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    due_date: Mapped[date | None] = mapped_column(Date)
    current_leg_id: Mapped[uuid.UUID | None] = uuid_fk("custody_history.id", nullable=True, use_alter=True)


class CustodyHistory(CreatedAtMixin, ActorSnapshotMixin, Base):
    """One leg per movement; the chain is the file's movement record (append-only). The actor snapshot is the
    sender or recaller."""

    __tablename__ = "custody_history"
    __table_class__ = TableClass.DERIVED
    __table_args__ = (
        UniqueConstraint("case_id", "seq_no"),
        CheckConstraint(f"reason IN {_in(CUSTODY_REASONS)}", name="reason"),
        CheckConstraint(f"reason NOT IN {_in(REMARK_REASONS)} OR remark IS NOT NULL", name="remark"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = uuid_fk("cases.id")
    seq_no: Mapped[int] = mapped_column(Integer, nullable=False)
    holder_office_id: Mapped[uuid.UUID] = uuid_fk("offices.id")
    holder_office_code: Mapped[str] = mapped_column(String(40), nullable=False)
    holder_user_id: Mapped[uuid.UUID | None] = uuid_fk("users.id", nullable=True, ondelete="SET NULL")
    holder_user_name: Mapped[str | None] = mapped_column(String(200))
    holder_membership_id: Mapped[uuid.UUID | None] = uuid_fk("user_memberships.id", nullable=True)
    holder_designation: Mapped[str | None] = mapped_column(String(200))
    reason: Mapped[str] = mapped_column(String(60), nullable=False)
    pending_action: Mapped[PendingAction] = mapped_column(
        pg_enum(PendingAction, "pending_action"), nullable=False, server_default="none"
    )
    due_date: Mapped[date | None] = mapped_column(Date)
    remark: Mapped[str | None] = mapped_column(String(2000))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class ResponseMode(enum.StrEnum):
    DEPARTMENT = "department"
    COUNSEL = "counsel"
    NONE = "none"


class CaseStage(CreatedAtMixin, ActorSnapshotMixin, Base):
    __tablename__ = "case_stages"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (Index("ix_case_stages_case_created", "case_id", text("created_at DESC")),)
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = uuid_fk("cases.id")
    office_id: Mapped[uuid.UUID] = uuid_fk("offices.id")
    stage: Mapped[Stage] = ref_code(Stage, "ref_case_stage")
    response_mode: Mapped[ResponseMode] = mapped_column(
        pg_enum(ResponseMode, "response_mode"), nullable=False, server_default="department"
    )
    note: Mapped[str | None] = mapped_column(Text)


class NoteSource(enum.StrEnum):
    USER = "user"
    SYSTEM = "system"


class CaseNote(CreatedAtMixin, RefNoMixin, ActorSnapshotMixin, Base):
    """Append-only; a correction is a new note whose `supersedes_id` points at the old one. `drafted_at` is
    set when the note came from a draft (the draft's creation time)."""

    __tablename__ = "case_notes"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (
        UniqueConstraint("case_id", "seq_no"),
        CheckConstraint("supersedes_id <> id", name="not_self"),
        Index(
            "ix_case_notes_supersedes",
            "supersedes_id",
            unique=True,
            postgresql_where=text("supersedes_id IS NOT NULL"),
        ),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = uuid_fk("cases.id")
    seq_no: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[NoteKind] = ref_code(NoteKind, "ref_note_kind")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    visibility: Mapped[Visibility] = mapped_column(
        pg_enum(Visibility, "doc_visibility"), nullable=False, server_default="case_scope"
    )
    office_id: Mapped[uuid.UUID] = uuid_fk("offices.id")
    author_role: Mapped[str] = mapped_column(String(40), nullable=False)
    custody_leg_id: Mapped[uuid.UUID | None] = uuid_fk("custody_history.id", nullable=True)
    supersedes_id: Mapped[uuid.UUID | None] = uuid_fk("case_notes.id", nullable=True)
    source: Mapped[NoteSource] = mapped_column(
        pg_enum(NoteSource, "note_source"), nullable=False, server_default="user"
    )
    drafted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CaseNoteAttachment(CreatedAtMixin, Base):
    __tablename__ = "case_note_attachments"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (UniqueConstraint("note_id", "document_id"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    note_id: Mapped[uuid.UUID] = uuid_fk("case_notes.id")
    document_id: Mapped[uuid.UUID] = uuid_fk("documents.id")


class CaseNoteDraft(TimestampMixin, ActorSnapshotMixin, Base):
    """A note of the current holder, visible only to its author, editable and deletable while that membership
    holds the case; made permanent (a `case_notes` row) and deleted when the file moves (decisions 12-13). One
    of the two tables of a case's records the application may delete from (owner's rule of 7 Oct 2026)."""

    __tablename__ = "case_note_drafts"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (Index("ix_case_note_drafts_case_membership", "case_id", "membership_id"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = uuid_fk("cases.id")
    membership_id: Mapped[uuid.UUID] = uuid_fk("user_memberships.id")
    author_user_id: Mapped[uuid.UUID] = uuid_fk("users.id")
    custody_leg_id: Mapped[uuid.UUID] = uuid_fk("custody_history.id")
    kind: Mapped[NoteKind] = ref_code(NoteKind, "ref_note_kind")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    visibility: Mapped[Visibility] = mapped_column(pg_enum(Visibility, "doc_visibility"), nullable=False)
    supersedes_id: Mapped[uuid.UUID | None] = uuid_fk("case_notes.id", nullable=True)


class CaseNoteDraftDocument(CreatedAtMixin, Base):
    """A document already on the case, linked to a draft; becomes a `case_note_attachments` row on
    finalisation and is deleted with its draft (the document itself is never deleted)."""

    __tablename__ = "case_note_draft_documents"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (UniqueConstraint("draft_id", "document_id"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    draft_id: Mapped[uuid.UUID] = uuid_fk("case_note_drafts.id")
    document_id: Mapped[uuid.UUID] = uuid_fk("documents.id")


class SourcetraceIngestion(CreatedAtMixin, Base):
    """One row per attempt to send a document to SourceTrace (design `sourcetrace-connector`, decision 12):
    append-only, written only by `services/sourcetrace_ingest.py` in the transaction that records the outcome
    on the document. Never holds secrets, note text or internal documents."""

    __tablename__ = "sourcetrace_ingestions"
    __table_class__ = TableClass.DERIVED
    __table_args__ = (
        CheckConstraint(
            "(ok AND reference IS NOT NULL AND error_family IS NULL) OR "
            "(NOT ok AND error IS NOT NULL AND error_family IS NOT NULL)",
            name="outcome",
        ),
        Index("ix_sourcetrace_ingestions_document_created", "document_id", "created_at"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = uuid_fk("documents.id", ondelete="CASCADE", index=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    connector: Mapped[str] = mapped_column(String(40), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(200))
    error: Mapped[str | None] = mapped_column(Text)
    error_family: Mapped[str | None] = mapped_column(String(40))
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    metadata_sent: Mapped[dict] = mapped_column(JSONB, nullable=False)
    response: Mapped[dict | None] = mapped_column(JSONB)
