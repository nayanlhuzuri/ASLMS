"""Group 6 — documents (stored files) and court orders."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from aslms.db.base import (
    ActorSnapshotMixin,
    Base,
    OptionalRefNoMixin,
    TableClass,
    TimestampMixin,
    pg_enum,
    ref_code,
    uuid_fk,
    uuid_pk,
)
from aslms.domain.reference import DocType


class DocKind(enum.StrEnum):
    CAUSELIST = "causelist"
    ORDER = "order"
    UPLOAD = "upload"
    ATTACHMENT = "attachment"


class DocGroup(enum.StrEnum):
    COURT_RECORD = "court_record"
    COURT_FILING = "court_filing"
    INTERNAL = "internal"


class Visibility(enum.StrEnum):
    CASE_SCOPE = "case_scope"
    COUNSEL_SHARED = "counsel_shared"
    PRIVATE_TO_OFFICE = "private_to_office"


class ScanStatus(enum.StrEnum):
    PENDING = "pending"
    CLEAN = "clean"
    INFECTED = "infected"
    FAILED = "failed"
    SKIPPED = "skipped"  # court-issued PDFs fetched by the system


class TextStatus(enum.StrEnum):
    PENDING = "pending"
    EXTRACTED = "extracted"
    FAILED = "failed"
    NONE = "none"


class SourcetraceStatus(enum.StrEnum):
    NOT_APPLICABLE = "not_applicable"  # internal documents, never sent
    PENDING = "pending"
    INGESTED = "ingested"
    FAILED = "failed"


class Document(TimestampMixin, OptionalRefNoMixin, ActorSnapshotMixin, Base):
    __tablename__ = "documents"
    __table_class__ = TableClass.TRANSACTION
    id: Mapped[uuid.UUID] = uuid_pk()
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    storage_key: Mapped[str] = mapped_column(String(400), nullable=False)
    mime: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(300))
    kind: Mapped[DocKind] = mapped_column(pg_enum(DocKind, "doc_kind"), nullable=False)
    doc_type: Mapped[DocType] = ref_code(DocType, "ref_doc_type")
    doc_group: Mapped[DocGroup] = mapped_column(pg_enum(DocGroup, "doc_group"), nullable=False)
    case_id: Mapped[uuid.UUID | None] = uuid_fk("cases.id", nullable=True)
    doc_date: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(Text)
    visibility: Mapped[Visibility] = mapped_column(
        pg_enum(Visibility, "doc_visibility"), nullable=False, server_default="case_scope"
    )
    office_id: Mapped[uuid.UUID | None] = uuid_fk("offices.id", nullable=True)
    virus_scan_status: Mapped[ScanStatus] = mapped_column(
        pg_enum(ScanStatus, "scan_status"), nullable=False, server_default="pending"
    )
    scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    text_status: Mapped[TextStatus] = mapped_column(
        pg_enum(TextStatus, "text_status"), nullable=False, server_default="pending"
    )
    text_extracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sourcetrace_status: Mapped[SourcetraceStatus] = mapped_column(
        pg_enum(SourcetraceStatus, "sourcetrace_status"), nullable=False, server_default="not_applicable"
    )
    sourcetrace_ref: Mapped[str | None] = mapped_column(String(200))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    page_count: Mapped[int | None] = mapped_column(Integer)


class DocumentText(TimestampMixin, Base):
    __tablename__ = "document_text"
    __table_class__ = TableClass.TRANSACTION
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    page_count: Mapped[int | None] = mapped_column(Integer)
    full_text: Mapped[str | None] = mapped_column(Text)
    search_vector: Mapped[str | None] = mapped_column(TSVECTOR)


class OrderKind(enum.StrEnum):
    INTERIM = "interim"
    FINAL = "final"
    JUDGMENT = "judgment"


class DownloadStatus(enum.StrEnum):
    PENDING = "pending"
    STORED = "stored"
    FAILED = "failed"
    NOT_AVAILABLE = "not_available"


class Order(TimestampMixin, Base):
    """interimorder[] / finalorder[] of the dossier; the PDF from Show Order."""

    __tablename__ = "orders"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (UniqueConstraint("case_id", "order_no", "order_date"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = uuid_fk("cases.id")
    order_no: Mapped[str] = mapped_column(String(20), nullable=False)
    order_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    kind: Mapped[OrderKind] = mapped_column(pg_enum(OrderKind, "order_kind"), nullable=False)
    order_details: Mapped[str | None] = mapped_column(String(200))  # "ORDER" / "JUDGEMENT"
    order_judge_name: Mapped[str | None] = mapped_column(Text)
    date_judgement_pronounced: Mapped[date | None] = mapped_column(Date)
    date_judgement_reserved: Mapped[date | None] = mapped_column(Date)
    is_reportable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    document_id: Mapped[uuid.UUID | None] = uuid_fk("documents.id", nullable=True)
    download_status: Mapped[DownloadStatus] = mapped_column(
        pg_enum(DownloadStatus, "download_status"), nullable=False, server_default="pending", index=True
    )
    download_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_error: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[dict | None] = mapped_column(JSONB)
