"""Phase 2 — custody and workflow (plan §5.7; decisions log: eOffice-style custody, requests, guided stages).

Custody is never keyed in: it is derived from what happens — a claim or allotment puts the case with the owning
office / unit / officer, a request sends it to the office asked to act, an answer brings it back, a hand-over
moves it explicitly with a note. `custody` holds the current position (one row per case); `custody_history`
is the append-only trail of legs."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from aslms.db.base import ActorSnapshotMixin, Base, CreatedAtMixin, TimestampMixin, pg_enum, uuid_fk, uuid_pk


class CustodyReason(enum.StrEnum):
    CLAIM = "claim"
    ALLOT = "allot"
    TRANSFER = "transfer"
    REQUEST_SENT = "request_sent"
    REQUEST_ANSWERED = "request_answered"
    REQUEST_WITHDRAWN = "request_withdrawn"
    HANDOVER = "handover"
    RELEASE = "release"


class Custody(TimestampMixin, Base):
    """Where the case is right now."""

    __tablename__ = "custody"

    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), primary_key=True
    )
    holder_office_id: Mapped[uuid.UUID] = uuid_fk("offices.id", ondelete="RESTRICT")
    holder_user_id: Mapped[uuid.UUID | None] = uuid_fk("users.id", nullable=True, ondelete="SET NULL")
    pending_action: Mapped[str | None] = mapped_column(String(300))
    since: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date)
    request_id: Mapped[uuid.UUID | None] = uuid_fk(
        "requests.id", nullable=True, ondelete="SET NULL", index=False
    )
    current_leg_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class CustodyHistory(CreatedAtMixin, ActorSnapshotMixin, Base):
    """Append-only trail: one row per custody leg (ground rule 3; triggers in migration 0003)."""

    __tablename__ = "custody_history"
    __table_args__ = (Index("ix_custody_history_case_started", "case_id", text("started_at DESC")),)

    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = uuid_fk("cases.id", index=False)
    seq_no: Mapped[int] = mapped_column(Integer, nullable=False)
    holder_office_id: Mapped[uuid.UUID] = uuid_fk("offices.id", ondelete="RESTRICT")
    holder_office_code: Mapped[str] = mapped_column(String(64), nullable=False)  # snapshot
    holder_user_id: Mapped[uuid.UUID | None] = uuid_fk(
        "users.id", nullable=True, ondelete="SET NULL", index=False
    )
    holder_user_name: Mapped[str | None] = mapped_column(String(200))  # snapshot
    reason: Mapped[CustodyReason] = mapped_column(pg_enum(CustodyReason, "custody_reason"), nullable=False)
    pending_action: Mapped[str | None] = mapped_column(String(300))
    due_date: Mapped[date | None] = mapped_column(Date)
    request_id: Mapped[uuid.UUID | None] = uuid_fk(
        "requests.id", nullable=True, ondelete="SET NULL", index=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RequestKind(enum.StrEnum):
    RECORDS = "records"  # petition, notice, annexures
    REPORT = "report"  # parawise comments / report from a directorate
    INSTRUCTIONS = "instructions"  # instructions to standing counsel
    VIEWS = "views"  # views of a referral department
    SIGNATURE = "signature"  # affidavit signature
    IMPLEMENTATION = "implementation"  # compliance with a court order
    BRIEF = "brief"  # brief from standing counsel
    OTHER = "other"


class RequestStatus(enum.StrEnum):
    OPEN = "open"
    ANSWERED = "answered"
    WITHDRAWN = "withdrawn"


class Request(TimestampMixin, ActorSnapshotMixin, Base):
    """Office-to-office request with a due date (plan §5.7). Sending it moves custody to `to_office`."""

    __tablename__ = "requests"
    __table_args__ = (
        Index("ix_requests_to_office_status", "to_office_id", "status"),
        Index("ix_requests_case", "case_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = uuid_fk("cases.id", index=False)
    kind: Mapped[RequestKind] = mapped_column(pg_enum(RequestKind, "request_kind"), nullable=False)
    from_office_id: Mapped[uuid.UUID] = uuid_fk("offices.id", ondelete="RESTRICT")
    to_office_id: Mapped[uuid.UUID] = uuid_fk("offices.id", ondelete="RESTRICT", index=False)
    to_user_id: Mapped[uuid.UUID | None] = uuid_fk(
        "users.id", nullable=True, ondelete="SET NULL", index=False
    )
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[RequestStatus] = mapped_column(
        pg_enum(RequestStatus, "request_status"), nullable=False, server_default=RequestStatus.OPEN.value
    )
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answered_by_user_id: Mapped[uuid.UUID | None] = uuid_fk(
        "users.id", nullable=True, ondelete="SET NULL", index=False
    )


class RequestMessage(CreatedAtMixin, ActorSnapshotMixin, Base):
    __tablename__ = "request_messages"

    id: Mapped[uuid.UUID] = uuid_pk()
    request_id: Mapped[uuid.UUID] = uuid_fk("requests.id")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_answer: Mapped[bool] = mapped_column(nullable=False, server_default="false")


class Stage(enum.StrEnum):
    """Department lifecycle (decisions log). Guided, not enforced: any stage can be set; gaps are flagged."""

    NOTICE_RECEIVED = "notice_received"
    RECORDS_RECEIVED = "records_received"
    RESPONSE_MODE_DECIDED = "response_mode_decided"
    INPUTS_AWAITED = "inputs_awaited"
    INPUTS_RECEIVED = "inputs_received"
    REFERRAL_VIEWS_AWAITED = "referral_views_awaited"
    INSTRUCTIONS_SENT = "instructions_sent"
    AFFIDAVIT_FILED = "affidavit_filed"
    ORDER_UNDER_EXAMINATION = "order_under_examination"
    COMPLIANCE_IN_PROGRESS = "compliance_in_progress"
    COMPLIED = "complied"
    APPEAL_REVIEW_UNDER_CONSIDERATION = "appeal_review_under_consideration"
    APPEAL_REVIEW_INSTRUCTED = "appeal_review_instructed"
    APPEAL_REVIEW_FILED = "appeal_review_filed"
    CONTEMPT_NOTICE_RECEIVED = "contempt_notice_received"
    VAKALATNAMA_SENT = "vakalatnama_sent"
    APPEARANCE_ENTERED = "appearance_entered"


STAGE_ORDER = [s for s in Stage]


class CaseStage(CreatedAtMixin, ActorSnapshotMixin, Base):
    """Append-only: the latest row is the current stage."""

    __tablename__ = "case_stages"
    __table_args__ = (Index("ix_case_stages_case_created", "case_id", text("created_at DESC")),)

    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = uuid_fk("cases.id", index=False)
    office_id: Mapped[uuid.UUID] = uuid_fk("offices.id", ondelete="RESTRICT", index=False)
    stage: Mapped[Stage] = mapped_column(pg_enum(Stage, "case_stage"), nullable=False)
    response_mode: Mapped[str | None] = mapped_column(String(32))  # dept_led | directorate_led
    note: Mapped[str | None] = mapped_column(Text)


class NoteKind(enum.StrEnum):
    GENERAL = "general"
    HANDOVER = "handover"
    INSTRUCTION = "instruction"
    OPINION = "opinion"
    HEARING_NOTE = "hearing_note"
    COMPLIANCE = "compliance"
    DECISION = "decision"
    SYSTEM = "system"


class NoteVisibility(enum.StrEnum):
    CASE_SCOPE = "case_scope"
    COUNSEL_SHARED = "counsel_shared"
    PRIVATE_TO_OFFICE = "private_to_office"


class CaseNote(CreatedAtMixin, ActorSnapshotMixin, Base):
    """The noting trail (plan §5.8): append-only, never edited; a correction is a new note that supersedes the
    old one and both stay visible. Author snapshot frozen; per-case sequence number; custody leg recorded."""

    __tablename__ = "case_notes"
    __table_args__ = (
        UniqueConstraint("case_id", "seq_no"),
        Index("ix_case_notes_case_seq", "case_id", "seq_no"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = uuid_fk("cases.id", index=False)
    seq_no: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[NoteKind] = mapped_column(pg_enum(NoteKind, "note_kind"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    visibility: Mapped[NoteVisibility] = mapped_column(
        pg_enum(NoteVisibility, "note_visibility"),
        nullable=False,
        server_default=NoteVisibility.CASE_SCOPE.value,
    )
    office_id: Mapped[uuid.UUID] = uuid_fk("offices.id", ondelete="RESTRICT", index=False)
    author_role: Mapped[str] = mapped_column(String(32), nullable=False)
    custody_leg_id: Mapped[uuid.UUID | None] = uuid_fk(
        "custody_history.id", nullable=True, ondelete="SET NULL", index=False
    )
    supersedes_id: Mapped[uuid.UUID | None] = uuid_fk(
        "case_notes.id", nullable=True, ondelete="SET NULL", index=False
    )
    source: Mapped[str | None] = mapped_column(
        String(32)
    )  # e.g. "assistant" when copied from the Case Assistant


class CaseNoteAttachment(CreatedAtMixin, Base):
    __tablename__ = "case_note_attachments"
    __table_args__ = (UniqueConstraint("note_id", "document_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    note_id: Mapped[uuid.UUID] = uuid_fk("case_notes.id")
    document_id: Mapped[uuid.UUID] = uuid_fk("documents.id", ondelete="RESTRICT")
