"""Group 4 — cause lists. NAPIX gives one list per (bench_id, causelist_id) per date; the website publishes one
court-wide PDF per list type; both are rows of `causelists` distinguished by `source`."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from aslms.db.base import Base, CreatedAtMixin, TableClass, TimestampMixin, pg_enum, uuid_fk, uuid_pk


class ListType(enum.StrEnum):
    DAILY = "daily"
    SUPPLEMENTARY = "supplementary"
    LAWAZIMA = "lawazima"
    VACATION = "vacation"
    OTHER = "other"


class ListSource(enum.StrEnum):
    NAPIX = "napix"
    GHC_WEBSITE = "ghc_website"
    LOCAL_DIR = "local_dir"


class FetchStatus(enum.StrEnum):
    PENDING = "pending"
    FETCHED = "fetched"
    FAILED = "failed"
    NOT_AVAILABLE = "not_available"


class ParseStatus(enum.StrEnum):
    PENDING = "pending"
    PARSED = "parsed"
    FAILED = "failed"
    EMPTY = "empty"


class CauselistBenchDay(CreatedAtMixin, Base):
    """Which benches sat on which day, as Cause List Bench reported it (bench ids change over time)."""

    __tablename__ = "causelist_bench_days"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (UniqueConstraint("court_id", "list_date", "bench_id"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    court_id: Mapped[uuid.UUID] = uuid_fk("courts.id")
    list_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    bench_id: Mapped[int] = mapped_column(Integer, nullable=False)
    judge_names_as_listed: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[dict | None] = mapped_column(JSONB)


class Causelist(TimestampMixin, Base):
    __tablename__ = "causelists"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (
        UniqueConstraint(
            "court_id",
            "list_date",
            "bench_id",
            "napix_causelist_id",
            "source",
            "list_type",
            postgresql_nulls_not_distinct=True,
        ),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    court_id: Mapped[uuid.UUID] = uuid_fk("courts.id")
    list_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    bench_id: Mapped[int | None] = mapped_column(Integer)  # NAPIX bench id; null for a court-wide file
    napix_causelist_id: Mapped[int | None] = mapped_column(Integer)
    list_type: Mapped[ListType] = mapped_column(pg_enum(ListType, "list_type"), nullable=False)
    list_type_text: Mapped[str | None] = mapped_column(String(100))  # cause_list_type, trimmed
    bench_label: Mapped[str | None] = mapped_column(Text)  # details `bench`
    label: Mapped[str | None] = mapped_column(String(200))
    source: Mapped[ListSource] = mapped_column(pg_enum(ListSource, "list_source"), nullable=False)
    document_id: Mapped[uuid.UUID | None] = uuid_fk("documents.id", nullable=True, use_alter=True)
    fetch_status: Mapped[FetchStatus] = mapped_column(
        pg_enum(FetchStatus, "fetch_status"), nullable=False, server_default="pending"
    )
    parse_status: Mapped[ParseStatus] = mapped_column(
        pg_enum(ParseStatus, "parse_status"), nullable=False, server_default="pending"
    )
    entry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[dict | None] = mapped_column(JSONB)


class EntrySource(enum.StrEnum):
    NAPIX_DETAILS = "napix_details"
    PDF_PARSE = "pdf_parse"


class ResolutionStatus(enum.StrEnum):
    RESOLVED = "resolved"
    PROVISIONAL = "provisional"
    UNRESOLVED = "unresolved"


class CauselistEntry(CreatedAtMixin, Base):
    """One printed row of a cause list. Immutable once written."""

    __tablename__ = "causelist_entries"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (UniqueConstraint("causelist_id", "source", "sr_no"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    causelist_id: Mapped[uuid.UUID] = uuid_fk("causelists.id")
    sr_no: Mapped[int] = mapped_column(Integer, nullable=False)
    printed_sr_no: Mapped[str | None] = mapped_column(String(20))
    court_no: Mapped[str | None] = mapped_column(String(20))
    bench_text: Mapped[str | None] = mapped_column(Text)
    section: Mapped[str | None] = mapped_column(
        String(200)
    )  # heading above the row ("ORDERS", "FOR ADMISSION")
    cnr: Mapped[str | None] = mapped_column(String(16), index=True)
    case_id: Mapped[uuid.UUID | None] = uuid_fk("cases.id", nullable=True)
    case_no_text: Mapped[str | None] = mapped_column(String(200), index=True)
    is_connected: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    petitioner_text: Mapped[str | None] = mapped_column(Text)
    respondent_text: Mapped[str | None] = mapped_column(Text)
    pet_advocate_text: Mapped[str | None] = mapped_column(Text)
    res_advocate_text: Mapped[str | None] = mapped_column(Text)
    counsel_codes: Mapped[list[str]] = mapped_column(ARRAY(String(60)), nullable=False, server_default="{}")
    with_text: Mapped[str | None] = mapped_column(Text)
    remarks: Mapped[str | None] = mapped_column(Text)
    source: Mapped[EntrySource] = mapped_column(pg_enum(EntrySource, "entry_source"), nullable=False)
    resolution_status: Mapped[ResolutionStatus] = mapped_column(
        pg_enum(ResolutionStatus, "resolution_status"), nullable=False, server_default="unresolved"
    )
    raw: Mapped[dict | None] = mapped_column(JSONB)


class CauselistReconciliation(CreatedAtMixin, Base):
    __tablename__ = "causelist_reconciliations"
    __table_class__ = TableClass.DERIVED
    id: Mapped[uuid.UUID] = uuid_pk()
    causelist_id: Mapped[uuid.UUID] = uuid_fk("causelists.id", ondelete="CASCADE")
    cnr: Mapped[str | None] = mapped_column(String(16))
    in_napix: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    in_pdf: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    mismatch_fields: Mapped[dict | None] = mapped_column(JSONB)
