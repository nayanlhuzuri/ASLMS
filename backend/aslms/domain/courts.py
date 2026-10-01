"""Group 2 — court masters synced from NAPIX, and places (states, districts). Masters are synced, never typed;
rows absent upstream are deactivated, never deleted (DB_STANDARD §0 rule 2)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from aslms.db.base import Base, DeactivateMixin, TableClass, TimestampMixin, pg_enum, uuid_fk, uuid_pk


class HighCourt(TimestampMixin, DeactivateMixin, Base):
    """The NAPIX state master lists High Courts (18 = Gauhati)."""

    __tablename__ = "high_courts"
    __table_class__ = TableClass.MASTER
    id: Mapped[uuid.UUID] = uuid_pk()
    napix_state_code: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)


class CourtLevel(enum.StrEnum):
    HC = "hc"
    DC = "dc"


class Court(TimestampMixin, DeactivateMixin, Base):
    """An establishment (`est_code`), e.g. GAHC01 Principal Seat at Guwahati."""

    __tablename__ = "courts"
    __table_class__ = TableClass.MASTER
    id: Mapped[uuid.UUID] = uuid_pk()
    est_code: Mapped[str] = mapped_column(String(10), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    high_court_id: Mapped[uuid.UUID | None] = uuid_fk("high_courts.id", nullable=True)
    napix_bench_no: Mapped[int | None] = mapped_column(Integer)  # the bench master's bench_id (1–4)
    bench_location: Mapped[str | None] = mapped_column(String(200))
    court_level: Mapped[CourtLevel] = mapped_column(
        pg_enum(CourtLevel, "court_level"), nullable=False, server_default="hc"
    )


class Bench(TimestampMixin, DeactivateMixin, Base):
    """A sitting bench as the cause lists and dossiers identify it (bench_id 2048, 2068 …)."""

    __tablename__ = "benches"
    __table_class__ = TableClass.MASTER
    __table_args__ = (UniqueConstraint("court_id", "bench_id"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    court_id: Mapped[uuid.UUID] = uuid_fk("courts.id")
    bench_id: Mapped[int] = mapped_column(Integer, nullable=False)
    judge_names: Mapped[str | None] = mapped_column(Text)
    bench_name: Mapped[str | None] = mapped_column(String(100))  # "Division Bench", from the dossier
    bench_type_code: Mapped[int | None] = mapped_column(Integer)
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class CaseType(TimestampMixin, DeactivateMixin, Base):
    __tablename__ = "case_types"
    __table_class__ = TableClass.MASTER
    __table_args__ = (UniqueConstraint("court_id", "case_type_code"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    court_id: Mapped[uuid.UUID] = uuid_fk("courts.id")
    case_type_code: Mapped[int] = mapped_column(Integer, nullable=False)
    type_name: Mapped[str] = mapped_column(String(300), nullable=False)  # as the master gives it
    short_name: Mapped[str | None] = mapped_column(String(60), index=True)  # "WA"
    full_name: Mapped[str | None] = mapped_column(String(300))  # "Writ Appeal"
    aliases: Mapped[list[str]] = mapped_column(ARRAY(String(60)), nullable=False, server_default="{}")


class State(TimestampMixin, DeactivateMixin, Base):
    __tablename__ = "states"
    __table_class__ = TableClass.MASTER
    id: Mapped[uuid.UUID] = uuid_pk()
    lgd_code: Mapped[int | None] = mapped_column(Integer, unique=True)
    ecourts_code: Mapped[int | None] = mapped_column(Integer, unique=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)


class DistrictKind(enum.StrEnum):
    DISTRICT = "district"
    AGENCY = "agency"  # CBI, NIA, C/O 99 APO in the eCourts list


class District(TimestampMixin, DeactivateMixin, Base):
    __tablename__ = "districts"
    __table_class__ = TableClass.MASTER
    __table_args__ = (UniqueConstraint("state_id", "name"), UniqueConstraint("high_court_id", "ecourts_code"))
    id: Mapped[uuid.UUID] = uuid_pk()
    state_id: Mapped[uuid.UUID] = uuid_fk("states.id")
    high_court_id: Mapped[uuid.UUID | None] = uuid_fk("high_courts.id", nullable=True)
    lgd_code: Mapped[int | None] = mapped_column(Integer, unique=True)
    ecourts_code: Mapped[int | None] = mapped_column(Integer)
    ecourts_name: Mapped[str | None] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    kind: Mapped[DistrictKind] = mapped_column(
        pg_enum(DistrictKind, "district_kind"), nullable=False, server_default="district"
    )


class Act(TimestampMixin, DeactivateMixin, Base):
    """The NAPIX act master repeats a national act code for several acts (375 codes carry two to four names)
    and a name under several codes, so the natural key is the pair (migration 0002)."""

    __tablename__ = "acts"
    __table_class__ = TableClass.MASTER
    __table_args__ = (UniqueConstraint("national_act_code", "name"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    national_act_code: Mapped[str | None] = mapped_column(String(20), index=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False, index=True)


class Advocate(TimestampMixin, DeactivateMixin, Base):
    __tablename__ = "advocates"
    __table_class__ = TableClass.MASTER
    id: Mapped[uuid.UUID] = uuid_pk()
    bar_reg_no: Mapped[str | None] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    name_normalised: Mapped[str] = mapped_column(String(200), nullable=False, index=True)


class MasterKind(enum.StrEnum):
    STATE = "state"
    DISTRICT = "district"
    BENCH = "bench"
    CASE_TYPE = "case_type"
    ACT = "act"


class MasterSyncRun(Base):
    __tablename__ = "master_sync_runs"
    __table_class__ = TableClass.DERIVED
    id: Mapped[uuid.UUID] = uuid_pk()
    master: Mapped[MasterKind] = mapped_column(pg_enum(MasterKind, "master_kind"), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    inserted: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    deactivated: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    sha256: Mapped[str | None] = mapped_column(String(64))
