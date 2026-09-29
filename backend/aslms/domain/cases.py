"""Group 3 — cases: the canonical case (CNR), parties, advocates, hearings, acts, links, raw snapshots."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
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
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aslms.db.base import Base, CreatedAtMixin, TableClass, TimestampMixin, pg_enum, uuid_fk, uuid_pk


class CaseStatus(enum.StrEnum):
    PENDING = "pending"
    DISPOSED = "disposed"
    UNKNOWN = "unknown"


class FirstSeenSource(enum.StrEnum):
    CAUSELIST = "causelist"
    SEARCH = "search"
    DISCOVERY = "discovery"
    LINK = "link"


class Case(TimestampMixin, Base):
    """Never fabricate a CNR. A case that has no CNR yet is `is_provisional = true` with `cnr` NULL."""

    __tablename__ = "cases"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (
        Index("ix_cases_court_type_no_year", "court_id", "case_type_id", "reg_no", "reg_year"),
        Index("ix_cases_next_hearing", "next_hearing_date"),
        Index("ix_cases_search_vector", "search_vector", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    cnr: Mapped[str | None] = mapped_column(String(16), unique=True)
    court_id: Mapped[uuid.UUID] = uuid_fk("courts.id", ondelete="RESTRICT")
    case_type_id: Mapped[uuid.UUID | None] = uuid_fk("case_types.id", nullable=True, ondelete="SET NULL")
    case_type_text: Mapped[str | None] = mapped_column(String(64))  # as printed, until normalised
    reg_no: Mapped[int | None] = mapped_column(Integer)
    reg_year: Mapped[int | None] = mapped_column(Integer)
    case_no_text: Mapped[str | None] = mapped_column(String(120))
    filing_no_text: Mapped[str | None] = mapped_column(String(120))
    filing_date: Mapped[date | None] = mapped_column(Date)
    registration_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[CaseStatus] = mapped_column(
        pg_enum(CaseStatus, "case_status"), nullable=False, server_default=CaseStatus.UNKNOWN.value
    )
    disposal_date: Mapped[date | None] = mapped_column(Date)
    disposal_nature: Mapped[str | None] = mapped_column(String(200))
    next_hearing_date: Mapped[date | None] = mapped_column(Date)
    next_purpose: Mapped[str | None] = mapped_column(String(300))
    last_hearing_date: Mapped[date | None] = mapped_column(Date)
    bench_id: Mapped[uuid.UUID | None] = uuid_fk("benches.id", nullable=True, ondelete="SET NULL")
    coram: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(300))
    judicial_branch: Mapped[str | None] = mapped_column(String(200))
    petitioner_summary: Mapped[str | None] = mapped_column(Text)
    respondent_summary: Mapped[str | None] = mapped_column(Text)
    pet_advocate: Mapped[str | None] = mapped_column(Text)
    res_advocate: Mapped[str | None] = mapped_column(Text)
    is_provisional: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_tracked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    first_seen_source: Mapped[FirstSeenSource] = mapped_column(
        pg_enum(FirstSeenSource, "first_seen_source"), nullable=False
    )
    last_full_refresh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status_refresh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    merged_into_case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="SET NULL"), nullable=True
    )
    search_vector: Mapped[Any | None] = mapped_column(TSVECTOR)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    parties: Mapped[list[CaseParty]] = relationship(back_populates="case", cascade="all, delete-orphan")
    advocates: Mapped[list[CaseAdvocate]] = relationship(back_populates="case", cascade="all, delete-orphan")


class PartyRole(enum.StrEnum):
    PETITIONER = "petitioner"
    RESPONDENT = "respondent"
    EXTRA = "extra"


class CaseParty(CreatedAtMixin, Base):
    __tablename__ = "case_parties"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (
        UniqueConstraint("case_id", "role", "party_no"),
        Index("ix_case_parties_name_normalised", "name_normalised"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = uuid_fk("cases.id")
    role: Mapped[PartyRole] = mapped_column(pg_enum(PartyRole, "party_role"), nullable=False)
    party_no: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    name_normalised: Mapped[str] = mapped_column(Text, nullable=False)
    address: Mapped[str | None] = mapped_column(Text)

    case: Mapped[Case] = relationship(back_populates="parties")


class AdvocateSide(enum.StrEnum):
    PETITIONER = "petitioner"
    RESPONDENT = "respondent"
    EXTRA = "extra"


class CaseAdvocate(CreatedAtMixin, Base):
    __tablename__ = "case_advocates"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (Index("ix_case_advocates_counsel_code", "counsel_code"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = uuid_fk("cases.id")
    side: Mapped[AdvocateSide] = mapped_column(pg_enum(AdvocateSide, "advocate_side"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    bar_reg_no: Mapped[str | None] = mapped_column(String(64))
    counsel_code: Mapped[str | None] = mapped_column(String(64))  # e.g. "SC, EDU" when printed

    case: Mapped[Case] = relationship(back_populates="advocates")


class HearingSource(enum.StrEnum):
    CNR_HISTORY = "cnr_history"
    SHOW_BUSINESS = "show_business"
    CAUSELIST = "causelist"
    CURRENT_STATUS = "current_status"


class CaseHearing(CreatedAtMixin, Base):
    __tablename__ = "case_hearings"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (UniqueConstraint("case_id", "business_date", "purpose"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = uuid_fk("cases.id")
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    purpose: Mapped[str] = mapped_column(String(300), nullable=False, server_default="")
    bench_text: Mapped[str | None] = mapped_column(Text)
    next_date: Mapped[date | None] = mapped_column(Date)
    business_text: Mapped[str | None] = mapped_column(Text)
    source: Mapped[HearingSource] = mapped_column(pg_enum(HearingSource, "hearing_source"), nullable=False)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class CaseAct(CreatedAtMixin, Base):
    __tablename__ = "case_acts"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (UniqueConstraint("case_id", "act_name", "section"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = uuid_fk("cases.id")
    act_name: Mapped[str] = mapped_column(String(300), nullable=False)
    national_act_code: Mapped[str | None] = mapped_column(String(32))
    section: Mapped[str] = mapped_column(String(200), nullable=False, server_default="")


class LinkKind(enum.StrEnum):
    MAIN_MATTER = "main_matter"
    CONNECTED = "connected"
    IA_IN = "ia_in"
    APPEAL_OF = "appeal_of"
    CONTEMPT_OF = "contempt_of"
    WITH = "with"


class LinkSource(enum.StrEnum):
    CNR_API = "cnr_api"
    CAUSELIST = "causelist"
    MANUAL = "manual"


class CaseLink(CreatedAtMixin, Base):
    """`to_case_id` is NULL while the target is only known by number (`to_case_no_text`)."""

    __tablename__ = "case_links"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (UniqueConstraint("from_case_id", "to_case_no_text", "kind"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    from_case_id: Mapped[uuid.UUID] = uuid_fk("cases.id")
    to_case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="SET NULL"), nullable=True, index=True
    )
    to_case_no_text: Mapped[str] = mapped_column(String(120), nullable=False)
    to_cnr: Mapped[str | None] = mapped_column(String(16))
    kind: Mapped[LinkKind] = mapped_column(pg_enum(LinkKind, "link_kind"), nullable=False)
    source: Mapped[LinkSource] = mapped_column(pg_enum(LinkSource, "link_source"), nullable=False)


class SnapshotSource(enum.StrEnum):
    CNR_API = "cnr_api"
    CURRENT_STATUS = "current_status"


class CaseSnapshot(CreatedAtMixin, Base):
    """Verbatim court record as fetched. Diffing consecutive snapshots yields status / next-date events."""

    __tablename__ = "case_snapshots"
    __table_class__ = TableClass.DERIVED
    __table_args__ = (
        UniqueConstraint("case_id", "payload_sha256"),
        Index("ix_case_snapshots_case_fetched", "case_id", text("fetched_at DESC")),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = uuid_fk("cases.id")
    source: Mapped[SnapshotSource] = mapped_column(pg_enum(SnapshotSource, "snapshot_source"), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
