"""Group 2 — reference data from the NAPIX masters: courts (establishments), benches, case types."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from aslms.db.base import Base, CreatedAtMixin, TimestampMixin, pg_enum, uuid_fk, uuid_pk


class CourtLevel(enum.StrEnum):
    HC = "hc"
    DC = "dc"


class Court(TimestampMixin, Base):
    """One row per NAPIX establishment (`est_code`), e.g. GAHC01 = Gauhati High Court, Principal Seat."""

    __tablename__ = "courts"

    id: Mapped[uuid.UUID] = uuid_pk()
    est_code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    state_code: Mapped[str] = mapped_column(String(8), nullable=False)
    bench_location: Mapped[str | None] = mapped_column(String(200))
    court_level: Mapped[CourtLevel] = mapped_column(pg_enum(CourtLevel, "court_level"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")


class Bench(TimestampMixin, Base):
    """Bench ids as NAPIX reports them for a cause-list date; they change from day to day, so every id is kept."""

    __tablename__ = "benches"
    __table_args__ = (UniqueConstraint("court_id", "bench_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    court_id: Mapped[uuid.UUID] = uuid_fk("courts.id")
    bench_id: Mapped[str] = mapped_column(String(32), nullable=False)
    judge_names: Mapped[str | None] = mapped_column(Text)
    bench_type: Mapped[str | None] = mapped_column(String(64))
    first_seen: Mapped[date] = mapped_column(Date, nullable=False)
    last_seen: Mapped[date] = mapped_column(Date, nullable=False)


class CaseType(TimestampMixin, Base):
    """Case Type Master: numeric `case_type` code ↔ `type_name` (e.g. WP(C)). `aliases` hold the spellings
    that cause lists print, so entries can be normalised to a code."""

    __tablename__ = "case_types"
    __table_args__ = (UniqueConstraint("court_id", "case_type_code"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    court_id: Mapped[uuid.UUID] = uuid_fk("courts.id")
    case_type_code: Mapped[int] = mapped_column(Integer, nullable=False)
    type_name: Mapped[str] = mapped_column(String(64), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(300))
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")


class MasterKind(enum.StrEnum):
    STATE = "state"
    DISTRICT = "district"
    BENCH = "bench"
    CASE_TYPE = "case_type"


class MasterSyncRun(CreatedAtMixin, Base):
    __tablename__ = "master_sync_runs"

    id: Mapped[uuid.UUID] = uuid_pk()
    master: Mapped[MasterKind] = mapped_column(pg_enum(MasterKind, "master_kind"), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
