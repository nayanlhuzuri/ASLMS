"""Group 6 — documents (stored files) and court orders."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID
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
    ADMIN = "admin"  # a document of an administrative record (admin ticket, membership), never of a case


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
    """A stored file: a cause-list or order PDF fetched by the pipeline, or a user's upload / note attachment
    (design `documents-uploads`). The store is content-addressed, so one file may back several rows; system
    PDFs are deduplicated per kind, uploads per (case, office) while not archived. Never deleted."""

    __tablename__ = "documents"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (
        Index("ix_documents_sha256", "sha256"),
        Index(
            "ix_documents_system_sha",
            "kind",
            "sha256",
            unique=True,
            postgresql_where=text("kind IN ('causelist', 'order')"),
        ),
        Index(
            "ix_documents_upload_dedupe",
            "case_id",
            "office_id",
            "sha256",
            unique=True,
            postgresql_where=text("kind = 'upload' AND archived_at IS NULL"),
        ),
        Index("ix_documents_case_kind", "case_id", "kind", postgresql_where=text("archived_at IS NULL")),
        CheckConstraint(
            "doc_group <> 'internal' OR sourcetrace_status = 'not_applicable'", name="internal_not_sent"
        ),
        CheckConstraint(
            "kind NOT IN ('upload', 'attachment', 'admin') OR (ref_no IS NOT NULL AND office_id IS NOT NULL "
            "AND doc_date IS NOT NULL AND virus_scan_status = 'clean' AND doc_group <> 'court_record')",
            name="user_file",
        ),
        CheckConstraint("kind <> 'upload' OR case_id IS NOT NULL", name="upload_case"),
        CheckConstraint(
            "kind <> 'admin' OR (case_id IS NULL AND doc_group = 'internal' AND visibility = 'private_to_office')",
            name="admin_file",
        ),
        CheckConstraint("archived_at IS NULL OR archive_reason IS NOT NULL", name="archive_reason"),
        # design sourcetrace-connector (migration 0011): only orders and uploads are ever sent, never a private
        # filing, and an ingested document carries SourceTrace's reference and the time
        CheckConstraint(
            "sourcetrace_status = 'not_applicable' OR kind IN ('order', 'upload')", name="sourcetrace_kind"
        ),
        CheckConstraint(
            "visibility <> 'private_to_office' OR sourcetrace_status = 'not_applicable'",
            name="private_not_sent",
        ),
        CheckConstraint(
            "sourcetrace_status <> 'ingested' OR (sourcetrace_ref IS NOT NULL AND sourcetrace_ingested_at IS NOT "
            "NULL)",
            name="sourcetrace_ingested",
        ),
        Index(
            "ix_documents_sourcetrace_due",
            "sourcetrace_next_at",
            postgresql_where=text("sourcetrace_status = 'pending'"),
        ),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
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
    # written only by services/sourcetrace_ingest.py, except the transitions of services/documents.py
    sourcetrace_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    sourcetrace_next_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sourcetrace_ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archive_reason: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int | None] = mapped_column(Integer)


class DocumentText(TimestampMixin, Base):
    """Written only by the text-extraction job (`services/text_extract.py`)."""

    __tablename__ = "document_text"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (Index("ix_document_text_search_vector_gin", "search_vector", postgresql_using="gin"),)
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


class OrderNextDateStatus(enum.StrEnum):
    """The reading of an order's next-date direction (design `next-date-extraction`, decision 4)."""

    PENDING = "pending"
    SPECIFIC = "specific"
    PERIOD = "period"
    UNCLEAR = "unclear"
    NONE = "none"
    NO_TEXT = "no_text"


class Order(TimestampMixin, Base):
    """interimorder[] / finalorder[] of the dossier; the PDF from Show Order. The `next_date_*` columns hold the
    reading of the order's stored text (written only by `services/next_dates.py`)."""

    __tablename__ = "orders"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (
        UniqueConstraint("case_id", "order_no", "order_date"),
        CheckConstraint(
            "(next_date_status IN ('specific', 'period')) = (next_date_found IS NOT NULL)",
            name="next_date_found",
        ),
        CheckConstraint(
            "(next_date_status = 'pending') = (next_date_read_at IS NULL)", name="next_date_read"
        ),
        Index(
            "ix_orders_next_date_pending",
            "created_at",
            postgresql_where=text("next_date_status = 'pending'"),
        ),
    )
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
    next_date_status: Mapped[OrderNextDateStatus] = mapped_column(
        pg_enum(OrderNextDateStatus, "order_next_date_status"), nullable=False, server_default="pending"
    )
    next_date_found: Mapped[date | None] = mapped_column(Date)
    next_date_rule: Mapped[str | None] = mapped_column(String(40))
    next_date_phrase: Mapped[str | None] = mapped_column(String(400))
    next_date_rules_version: Mapped[int | None] = mapped_column(SmallInteger)
    next_date_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OrderLayout(enum.StrEnum):
    """Design `order-sections`, decision 8: the court's template was found (a coram and a heading) or not."""

    TEMPLATE = "template"
    WHOLE = "whole"


class OrderOutcome(enum.StrEnum):
    """Decision 17: the outcome of the main matter, read by rule (`partly_allowed` and `closed` beside the owner's
    four)."""

    ALLOWED = "allowed"
    PARTLY_ALLOWED = "partly_allowed"
    DISMISSED = "dismissed"
    DISPOSED_OF = "disposed_of"
    WITHDRAWN = "withdrawn"
    CLOSED = "closed"


class OrderSectionFlag(enum.StrEnum):
    """Decision 15: intrinsic flags about the text itself (the live checks against `orders` and `cases` are never
    stored)."""

    OFF_TEMPLATE = "off_template"
    NO_CNR_LINE = "no_cnr_line"
    NO_CASE_NO = "no_case_no"
    NO_DATE = "no_date"
    PAGE_MARKS_DIFFER = "page_marks_differ"
    EMPTY_BODY = "empty_body"
    CAPPED = "capped"


class OrderSectionReplaceReason(enum.StrEnum):
    """Decision 18: why a reading was replaced by a newer one (`text_gone`: replaced with no successor)."""

    PARSER_VERSION = "parser_version"
    TEXT_REEXTRACTED = "text_reextracted"
    DOCUMENT_CHANGED = "document_changed"
    TEXT_GONE = "text_gone"


class OrderSection(TimestampMixin, Base):
    """One reading of a court order's stored text into its parts, by rules (design `order-sections`): spans and
    offsets into `document_text.full_text` (`src`) and the cleaned `body_text` (`txt`), 0-based code points, end
    exclusive. Derived and re-buildable; written only by `services/order_sections.py`. A row never changes except to
    be marked replaced once (`replaced_at`, `replaced_by_id`, `replace_reason`; trigger
    `order_sections_replace_once`); never deleted. One current row per order (`ix_order_sections_current`).
    Parties, advocates and coram are not copied, only their spans; mismatches with `orders` and `cases` are computed
    when read (decision 5)."""

    __tablename__ = "order_sections"
    __table_class__ = TableClass.DERIVED
    __table_args__ = (
        Index(
            "ix_order_sections_current", "order_id", unique=True, postgresql_where=text("replaced_at IS NULL")
        ),
        Index("ix_order_sections_order_created", "order_id", "created_at"),
        Index("ix_order_sections_body_sha256", "body_sha256", postgresql_where=text("replaced_at IS NULL")),
        # the research index's filters on cited judgments and acts (design research-index, decision 20; migration 0042)
        Index(
            "ix_order_sections_facts_judgments",
            text("(facts -> 'judgments') jsonb_path_ops"),
            postgresql_using="gin",
            postgresql_where=text("replaced_at IS NULL"),
        ),
        Index(
            "ix_order_sections_facts_acts",
            text("(facts -> 'acts') jsonb_path_ops"),
            postgresql_using="gin",
            postgresql_where=text("replaced_at IS NULL"),
        ),
        CheckConstraint("(replaced_at IS NULL) = (replace_reason IS NULL)", name="replaced"),
        CheckConstraint(
            "(replaced_by_id IS NULL OR replaced_at IS NOT NULL) AND (replace_reason IS NULL OR "
            "replace_reason = 'text_gone' OR replaced_by_id IS NOT NULL)",
            name="successor",
        ),
        CheckConstraint("layout = 'template' OR 'off_template' = ANY(flags)", name="whole"),
        CheckConstraint("NOT registrar OR procedural", name="registrar"),
        CheckConstraint("outcome IS NULL OR form <> 'interim'", name="outcome"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    order_id: Mapped[uuid.UUID] = uuid_fk("orders.id", index=False)
    document_id: Mapped[uuid.UUID] = uuid_fk("documents.id")
    pdf_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    text_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    text_chars: Mapped[int] = mapped_column(Integer, nullable=False)
    parser_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    layout: Mapped[OrderLayout] = mapped_column(pg_enum(OrderLayout, "order_layout"), nullable=False)
    form: Mapped[OrderKind] = mapped_column(pg_enum(OrderKind, "order_kind"), nullable=False)
    heading: Mapped[str | None] = mapped_column(String(80))
    oral: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    cav: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    printed_cnr: Mapped[str | None] = mapped_column(String(16))
    printed_case_no: Mapped[str | None] = mapped_column(String(80))
    printed_date: Mapped[date | None] = mapped_column(Date)
    printed_reserved_on: Mapped[date | None] = mapped_column(Date)
    printed_pronounced_on: Mapped[date | None] = mapped_column(Date)
    neutral_citation: Mapped[str | None] = mapped_column(String(40))
    author: Mapped[str | None] = mapped_column(String(200))
    registrar: Mapped[bool] = mapped_column(Boolean, nullable=False)
    procedural: Mapped[bool] = mapped_column(Boolean, nullable=False)
    outcome: Mapped[OrderOutcome | None] = mapped_column(pg_enum(OrderOutcome, "order_outcome"))
    spans: Mapped[dict] = mapped_column(JSONB, nullable=False)
    linked_cases: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    body_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    paragraphs: Mapped[list] = mapped_column(JSONB, nullable=False)
    parts: Mapped[list] = mapped_column(JSONB, nullable=False)
    facts: Mapped[dict] = mapped_column(JSONB, nullable=False)
    flags: Mapped[list[OrderSectionFlag]] = mapped_column(
        ARRAY(pg_enum(OrderSectionFlag, "order_section_flag")),
        nullable=False,
        server_default=text("'{}'"),
    )
    replaced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # deferred: the old row names its successor in the same savepoint before the successor's insert (decision 23)
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("order_sections.id", ondelete="RESTRICT", deferrable=True, initially="DEFERRED"),
        index=True,
    )
    replace_reason: Mapped[OrderSectionReplaceReason | None] = mapped_column(
        pg_enum(OrderSectionReplaceReason, "order_section_replace_reason")
    )
