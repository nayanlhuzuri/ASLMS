"""Phase 2 — custody and workflow, the noting trail, SourceTrace ingestion records."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, text
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
from aslms.domain.reference import NoteKind, RequestKind, Stage


class PendingAction(enum.StrEnum):
    NONE = "none"
    EXAMINE = "examine"
    REPLY = "reply"
    FILE = "file"
    COMPLY = "comply"
    REVIEW = "review"


class Custody(TimestampMixin, Base):
    """Where the case is now (1:1 with the case)."""

    __tablename__ = "custody"
    __table_class__ = TableClass.TRANSACTION
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="RESTRICT"), primary_key=True
    )
    holder_office_id: Mapped[uuid.UUID] = uuid_fk("offices.id")
    holder_user_id: Mapped[uuid.UUID | None] = uuid_fk("users.id", nullable=True, ondelete="SET NULL")
    pending_action: Mapped[PendingAction] = mapped_column(
        pg_enum(PendingAction, "pending_action"), nullable=False, server_default="none"
    )
    since: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    due_date: Mapped[date | None] = mapped_column(Date)
    request_id: Mapped[uuid.UUID | None] = uuid_fk("requests.id", nullable=True, use_alter=True)
    current_leg_id: Mapped[uuid.UUID | None] = uuid_fk("custody_history.id", nullable=True, use_alter=True)


class CustodyHistory(CreatedAtMixin, ActorSnapshotMixin, Base):
    __tablename__ = "custody_history"
    __table_class__ = TableClass.DERIVED
    __table_args__ = (UniqueConstraint("case_id", "seq_no"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = uuid_fk("cases.id")
    seq_no: Mapped[int] = mapped_column(Integer, nullable=False)
    holder_office_id: Mapped[uuid.UUID] = uuid_fk("offices.id")
    holder_office_code: Mapped[str] = mapped_column(String(40), nullable=False)
    holder_user_id: Mapped[uuid.UUID | None] = uuid_fk("users.id", nullable=True, ondelete="SET NULL")
    holder_user_name: Mapped[str | None] = mapped_column(String(200))
    reason: Mapped[str] = mapped_column(String(60), nullable=False)
    pending_action: Mapped[PendingAction] = mapped_column(
        pg_enum(PendingAction, "pending_action"), nullable=False, server_default="none"
    )
    due_date: Mapped[date | None] = mapped_column(Date)
    request_id: Mapped[uuid.UUID | None] = uuid_fk("requests.id", nullable=True, use_alter=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class RequestStatus(enum.StrEnum):
    OPEN = "open"
    ANSWERED = "answered"
    WITHDRAWN = "withdrawn"


class Request(TimestampMixin, RefNoMixin, ActorSnapshotMixin, Base):
    __tablename__ = "requests"
    __table_class__ = TableClass.TRANSACTION
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = uuid_fk("cases.id")
    kind: Mapped[RequestKind] = ref_code(RequestKind, "ref_request_kind")
    from_office_id: Mapped[uuid.UUID] = uuid_fk("offices.id")
    to_office_id: Mapped[uuid.UUID] = uuid_fk("offices.id")
    to_user_id: Mapped[uuid.UUID | None] = uuid_fk("users.id", nullable=True, ondelete="SET NULL")
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[RequestStatus] = mapped_column(
        pg_enum(RequestStatus, "request_status"), nullable=False, server_default="open", index=True
    )
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answered_by_user_id: Mapped[uuid.UUID | None] = uuid_fk("users.id", nullable=True, ondelete="SET NULL")
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RequestMessage(CreatedAtMixin, ActorSnapshotMixin, Base):
    __tablename__ = "request_messages"
    __table_class__ = TableClass.TRANSACTION
    id: Mapped[uuid.UUID] = uuid_pk()
    request_id: Mapped[uuid.UUID] = uuid_fk("requests.id")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_answer: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


class ResponseMode(enum.StrEnum):
    DEPARTMENT = "department"
    COUNSEL = "counsel"
    NONE = "none"


class CaseStage(CreatedAtMixin, ActorSnapshotMixin, Base):
    __tablename__ = "case_stages"
    __table_class__ = TableClass.TRANSACTION
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
    """Append-only; a correction is a new note whose `supersedes_id` points at the old one."""

    __tablename__ = "case_notes"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (UniqueConstraint("case_id", "seq_no"),)
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


class CaseNoteAttachment(CreatedAtMixin, Base):
    __tablename__ = "case_note_attachments"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (UniqueConstraint("note_id", "document_id"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    note_id: Mapped[uuid.UUID] = uuid_fk("case_notes.id")
    document_id: Mapped[uuid.UUID] = uuid_fk("documents.id")


class SourcetraceIngestion(CreatedAtMixin, Base):
    __tablename__ = "sourcetrace_ingestions"
    __table_class__ = TableClass.DERIVED
    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = uuid_fk("documents.id", ondelete="CASCADE")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reference: Mapped[str | None] = mapped_column(String(200))
    error: Mapped[str | None] = mapped_column(Text)
    metadata_sent: Mapped[dict | None] = mapped_column(JSONB)
