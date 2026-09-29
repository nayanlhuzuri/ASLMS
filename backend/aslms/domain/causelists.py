"""Group 4 — cause lists: one row per list publication, one immutable row per listed case, reconciliation."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aslms.db.base import Base, CreatedAtMixin, TableClass, TimestampMixin, pg_enum, uuid_fk, uuid_pk


class ListType(enum.StrEnum):
    DAILY = "daily"
    SUPPLEMENTARY = "supplementary"
    LAWAZIMA = "lawazima"
    VACATION = "vacation"
    OTHER = "other"


class CauseListSource(enum.StrEnum):
    NAPIX = "napix"
    GHC_WEBSITE = "ghc_website"
    LOCAL_DIR = "local_dir"


class FetchStatus(enum.StrEnum):
    PENDING = "pending"
    FETCHED = "fetched"
    NOT_AVAILABLE = "not_available"
    FAILED = "failed"


class ParseStatus(enum.StrEnum):
    PENDING = "pending"
    PARSED = "parsed"
    PARTIAL = "partial"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"


class CauseList(TimestampMixin, Base):
    __tablename__ = "causelists"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (
        UniqueConstraint("court_id", "list_date", "bench_id", "napix_causelist_id", "source"),
        Index("ix_causelists_list_date", "list_date"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    court_id: Mapped[uuid.UUID] = uuid_fk("courts.id", ondelete="RESTRICT")
    list_date: Mapped[date] = mapped_column(Date, nullable=False)
    bench_id: Mapped[str] = mapped_column(String(32), nullable=False, server_default="")  # NAPIX bench_id
    napix_causelist_id: Mapped[str] = mapped_column(String(64), nullable=False, server_default="")
    list_type: Mapped[ListType] = mapped_column(pg_enum(ListType, "list_type"), nullable=False)
    label: Mapped[str | None] = mapped_column(String(300))
    source: Mapped[CauseListSource] = mapped_column(
        pg_enum(CauseListSource, "causelist_source"), nullable=False
    )
    document_id: Mapped[uuid.UUID | None] = uuid_fk("documents.id", nullable=True, ondelete="RESTRICT")
    fetch_status: Mapped[FetchStatus] = mapped_column(
        pg_enum(FetchStatus, "fetch_status"), nullable=False, server_default=FetchStatus.PENDING.value
    )
    parse_status: Mapped[ParseStatus] = mapped_column(
        pg_enum(ParseStatus, "parse_status"), nullable=False, server_default=ParseStatus.PENDING.value
    )
    entry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    entries: Mapped[list[CauseListEntry]] = relationship(
        back_populates="causelist", cascade="all, delete-orphan"
    )


class EntrySource(enum.StrEnum):
    NAPIX_DETAILS = "napix_details"  # rows from the Cause List Details API
    PDF_PARSE = "pdf_parse"  # rows parsed from the Show Cause List / website PDF


class ResolutionStatus(enum.StrEnum):
    RESOLVED = "resolved"
    PROVISIONAL = "provisional"
    UNRESOLVED = "unresolved"


class CauseListEntry(CreatedAtMixin, Base):
    """One listed case, immutable once written. Both sources are kept side by side until the live NAPIX test
    shows whether Cause List Details is complete; `causelist_reconciliations` compares them."""

    __tablename__ = "causelist_entries"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (
        UniqueConstraint("causelist_id", "source", "sr_no"),
        Index("ix_causelist_entries_cnr", "cnr"),
        Index("ix_causelist_entries_case", "case_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    causelist_id: Mapped[uuid.UUID] = uuid_fk("causelists.id")
    sr_no: Mapped[int] = mapped_column(Integer, nullable=False)
    court_no: Mapped[str | None] = mapped_column(String(32))
    cnr: Mapped[str | None] = mapped_column(String(16))
    case_id: Mapped[uuid.UUID | None] = uuid_fk("cases.id", nullable=True, ondelete="RESTRICT", index=False)
    case_no_text: Mapped[str | None] = mapped_column(String(120))
    petitioner_text: Mapped[str | None] = mapped_column(Text)
    respondent_text: Mapped[str | None] = mapped_column(Text)
    pet_advocate_text: Mapped[str | None] = mapped_column(Text)
    res_advocate_text: Mapped[str | None] = mapped_column(Text)
    counsel_codes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    with_text: Mapped[str | None] = mapped_column(Text)
    remarks: Mapped[str | None] = mapped_column(Text)
    source: Mapped[EntrySource] = mapped_column(pg_enum(EntrySource, "entry_source"), nullable=False)
    resolution_status: Mapped[ResolutionStatus] = mapped_column(
        pg_enum(ResolutionStatus, "resolution_status"),
        nullable=False,
        server_default=ResolutionStatus.UNRESOLVED.value,
    )
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    causelist: Mapped[CauseList] = relationship(back_populates="entries")


class CauseListReconciliation(CreatedAtMixin, Base):
    __tablename__ = "causelist_reconciliations"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (UniqueConstraint("causelist_id", "cnr"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    causelist_id: Mapped[uuid.UUID] = uuid_fk("causelists.id", ondelete="CASCADE")  # §6: regenerable
    cnr: Mapped[str] = mapped_column(String(16), nullable=False)
    in_napix: Mapped[bool] = mapped_column(nullable=False)
    in_pdf: Mapped[bool] = mapped_column(nullable=False)
    mismatch_fields: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
