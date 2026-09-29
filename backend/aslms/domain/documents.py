"""Group 6 — documents and orders: every stored file (court orders, cause-list PDFs, uploads) and the
court-order records that point at them."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from aslms.db.base import (
    ActorSnapshotMixin,
    Base,
    CreatedAtMixin,
    OptionalRefNoMixin,
    TableClass,
    TimestampMixin,
    pg_enum,
    ref_code,
    uuid_fk,
    uuid_pk,
)


class DocumentKind(enum.StrEnum):
    COURT_ORDER = "court_order"
    CAUSELIST = "causelist"
    COURT_FILING = "court_filing"
    INTERNAL = "internal"
    OTHER = "other"


class DocType(enum.StrEnum):
    ORDER = "order"
    JUDGMENT = "judgment"
    CAUSELIST_PDF = "causelist_pdf"
    WRIT_PETITION = "writ_petition"
    AFFIDAVIT_IN_OPPOSITION = "affidavit_in_opposition"
    REPLY = "reply"
    REJOINDER = "rejoinder"
    IA = "ia"
    ANNEXURE = "annexure"
    COMPLIANCE_REPORT = "compliance_report"
    PARAWISE_COMMENTS = "parawise_comments"
    INSTRUCTIONS_TO_COUNSEL = "instructions_to_counsel"
    OTHER = "other"


class DocGroup(enum.StrEnum):
    COURT_RECORD = "court_record"  # collected from the court (orders, cause lists)
    COURT_FILING = "court_filing"  # filed in or received from the court; may go to SourceTrace
    INTERNAL = "internal"  # never leaves the portal


class Visibility(enum.StrEnum):
    CASE_SCOPE = "case_scope"
    COUNSEL_SHARED = "counsel_shared"
    PRIVATE_TO_OFFICE = "private_to_office"


class VirusScanStatus(enum.StrEnum):
    PENDING = "pending"
    CLEAN = "clean"
    INFECTED = "infected"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"


class TextStatus(enum.StrEnum):
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"


class SourceTraceStatus(enum.StrEnum):
    NOT_APPLICABLE = "not_applicable"
    PENDING = "pending"
    INGESTED = "ingested"
    FAILED = "failed"


class Document(TimestampMixin, OptionalRefNoMixin, ActorSnapshotMixin, Base):
    """One row per stored file, deduplicated on sha256. The actor columns record the uploader for
    user uploads; system-collected documents leave them NULL. Uploads (`court_filing` / `internal`) carry a
    `ref_no` (`DOC`); court records do not. Never deleted: `archived_at` retires a document."""

    __tablename__ = "documents"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (
        Index("ix_documents_case_kind", "case_id", "kind"),
        Index("ix_documents_sourcetrace_status", "sourcetrace_status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(400), nullable=False)
    mime: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(300))
    kind: Mapped[DocumentKind] = mapped_column(pg_enum(DocumentKind, "document_kind"), nullable=False)
    doc_type: Mapped[DocType] = ref_code(DocType, "ref_doc_type")
    doc_group: Mapped[DocGroup] = mapped_column(pg_enum(DocGroup, "doc_group"), nullable=False)
    case_id: Mapped[uuid.UUID | None] = uuid_fk("cases.id", nullable=True, ondelete="RESTRICT", index=False)
    doc_date: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(Text)
    visibility: Mapped[Visibility] = mapped_column(
        pg_enum(Visibility, "visibility"), nullable=False, server_default=Visibility.CASE_SCOPE.value
    )
    office_id: Mapped[uuid.UUID | None] = uuid_fk("offices.id", nullable=True, ondelete="SET NULL")
    virus_scan_status: Mapped[VirusScanStatus] = mapped_column(
        pg_enum(VirusScanStatus, "virus_scan_status"),
        nullable=False,
        server_default=VirusScanStatus.PENDING.value,
    )
    scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    text_status: Mapped[TextStatus] = mapped_column(
        pg_enum(TextStatus, "text_status"), nullable=False, server_default=TextStatus.PENDING.value
    )
    text_extracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sourcetrace_status: Mapped[SourceTraceStatus] = mapped_column(
        pg_enum(SourceTraceStatus, "sourcetrace_status"),
        nullable=False,
        server_default=SourceTraceStatus.NOT_APPLICABLE.value,
    )
    sourcetrace_ref: Mapped[str | None] = mapped_column(String(200))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentText(CreatedAtMixin, Base):
    """Extracted text kept apart so `documents` stays narrow. `search_vector` drives content search."""

    __tablename__ = "document_text"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (Index("ix_document_text_search_vector", "search_vector", postgresql_using="gin"),)

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    page_count: Mapped[int | None] = mapped_column(Integer)
    full_text: Mapped[str] = mapped_column(Text, nullable=False)
    search_vector: Mapped[Any | None] = mapped_column(TSVECTOR)


class OrderKind(enum.StrEnum):
    INTERIM = "interim"
    FINAL = "final"
    JUDGMENT = "judgment"


class DownloadStatus(enum.StrEnum):
    PENDING = "pending"
    DOWNLOADED = "downloaded"
    NOT_AVAILABLE = "not_available"
    FAILED = "failed"


class Order(TimestampMixin, Base):
    """A court order or judgment as listed in the CNR response; `document_id` is set once Show Order
    has delivered the PDF."""

    __tablename__ = "orders"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (
        UniqueConstraint("case_id", "order_no", "order_date"),
        Index("ix_orders_download_status", "download_status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = uuid_fk("cases.id")
    order_no: Mapped[str] = mapped_column(String(32), nullable=False)
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    kind: Mapped[OrderKind] = mapped_column(pg_enum(OrderKind, "order_kind"), nullable=False)
    is_reportable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    document_id: Mapped[uuid.UUID | None] = uuid_fk("documents.id", nullable=True, ondelete="RESTRICT")
    download_status: Mapped[DownloadStatus] = mapped_column(
        pg_enum(DownloadStatus, "download_status"),
        nullable=False,
        server_default=DownloadStatus.PENDING.value,
    )
    download_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
