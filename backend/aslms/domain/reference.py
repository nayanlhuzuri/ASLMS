"""Group 2 — reference data.

Two kinds live here (DB_STANDARD §0):
* court masters synced from NAPIX: courts (establishments), benches, case types, and the sync log;
* the `ref_*` code sets (§7): the eight enumerations users see as labels, filter on, or that an administrator
  may extend without a release, plus `ref_record_type` for reference numbers (§3) and `ref_sequences`
  (Appendix C). Their rows are seeded from the Python enums, whose values are the codes."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from aslms.db.base import (
    Base,
    CreatedAtMixin,
    DeactivateMixin,
    TableClass,
    TimestampMixin,
    pg_enum,
    uuid_fk,
    uuid_pk,
)


# ------------------------------------------------------------------------------------------ court masters
class CourtLevel(enum.StrEnum):
    HC = "hc"
    DC = "dc"


class Court(TimestampMixin, DeactivateMixin, Base):
    """One row per NAPIX establishment (`est_code`), e.g. GAHC01 = Gauhati High Court, Principal Seat."""

    __tablename__ = "courts"
    __table_class__ = TableClass.MASTER

    id: Mapped[uuid.UUID] = uuid_pk()
    est_code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    state_code: Mapped[str] = mapped_column(String(8), nullable=False)
    bench_location: Mapped[str | None] = mapped_column(String(200))
    court_level: Mapped[CourtLevel] = mapped_column(pg_enum(CourtLevel, "court_level"), nullable=False)


class Bench(TimestampMixin, DeactivateMixin, Base):
    """Bench ids as NAPIX reports them for a cause-list date; they change from day to day, so every id is kept."""

    __tablename__ = "benches"
    __table_class__ = TableClass.MASTER
    __table_args__ = (UniqueConstraint("court_id", "bench_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    court_id: Mapped[uuid.UUID] = uuid_fk("courts.id")
    bench_id: Mapped[str] = mapped_column(String(32), nullable=False)
    judge_names: Mapped[str | None] = mapped_column(Text)
    bench_type: Mapped[str | None] = mapped_column(String(64))
    first_seen: Mapped[date] = mapped_column(Date, nullable=False)
    last_seen: Mapped[date] = mapped_column(Date, nullable=False)


class CaseType(TimestampMixin, DeactivateMixin, Base):
    """Case Type Master: numeric `case_type` code ↔ `type_name` (e.g. WP(C)). `aliases` hold the spellings
    that cause lists print, so entries can be normalised to a code."""

    __tablename__ = "case_types"
    __table_class__ = TableClass.MASTER
    __table_args__ = (UniqueConstraint("court_id", "case_type_code"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    court_id: Mapped[uuid.UUID] = uuid_fk("courts.id")
    case_type_code: Mapped[int] = mapped_column(Integer, nullable=False)
    type_name: Mapped[str] = mapped_column(String(64), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(300))
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")


class MasterKind(enum.StrEnum):
    STATE = "state"
    DISTRICT = "district"
    BENCH = "bench"
    CASE_TYPE = "case_type"
    ACT = "act"


class MasterSyncRun(CreatedAtMixin, Base):
    __tablename__ = "master_sync_runs"
    __table_class__ = TableClass.DERIVED

    id: Mapped[uuid.UUID] = uuid_pk()
    master: Mapped[MasterKind] = mapped_column(pg_enum(MasterKind, "master_kind"), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)


# ------------------------------------------------------------------------------------------ code sets (§7)
class RefMixin(TimestampMixin):
    """Shape of every `ref_*` table: `code` is the key (the Python enum value); labels are data."""

    __table_class__ = TableClass.REFERENCE

    code: Mapped[str] = mapped_column(String(40), primary_key=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")


class RefRole(RefMixin, Base):
    __tablename__ = "ref_role"


class RefOfficeKind(RefMixin, Base):
    __tablename__ = "ref_office_kind"


class RefCaseStage(RefMixin, Base):
    """The department lifecycle as an ordered list; `phase` groups the main track, appeal/review, contempt
    and counsel steps."""

    __tablename__ = "ref_case_stage"

    phase: Mapped[str] = mapped_column(String(20), nullable=False, server_default="main")


class RefRequestKind(RefMixin, Base):
    __tablename__ = "ref_request_kind"


class RefNoteKind(RefMixin, Base):
    __tablename__ = "ref_note_kind"


class RefDocType(RefMixin, Base):
    """The filing vocabulary; `doc_group` says whether a type is a court record, a court filing (may go to
    SourceTrace) or internal (never leaves the portal)."""

    __tablename__ = "ref_doc_type"

    doc_group: Mapped[str] = mapped_column(String(20), nullable=False)


class RefAlertKind(RefMixin, Base):
    __tablename__ = "ref_alert_kind"

    default_severity: Mapped[str] = mapped_column(String(20), nullable=False, server_default="normal")


class RefEventType(RefMixin, Base):
    """Timeline labels live in data, not code."""

    __tablename__ = "ref_event_type"

    timeline_label: Mapped[str] = mapped_column(String(120), nullable=False)
    icon_key: Mapped[str | None] = mapped_column(String(40))
    is_tracking_card: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")


class RefRecordType(RefMixin, Base):
    """`TYPE` in `ASLMS/<OFFICE>/<TYPE>/<YYYY>/<NNNNNN>` (§3)."""

    __tablename__ = "ref_record_type"


class RefSequence(Base):
    """One counter per (allocating office, record type, year); locked row by row by `allocate_ref_no`."""

    __tablename__ = "ref_sequences"
    __table_class__ = TableClass.DERIVED

    office_code: Mapped[str] = mapped_column(String(20), primary_key=True)
    record_type: Mapped[str] = mapped_column(
        String(10), ForeignKey("ref_record_type.code", ondelete="RESTRICT"), primary_key=True
    )
    year: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    last_value: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


REF_TABLES: tuple[type[Base], ...] = (
    RefRole,
    RefOfficeKind,
    RefCaseStage,
    RefRequestKind,
    RefNoteKind,
    RefDocType,
    RefAlertKind,
    RefEventType,
    RefRecordType,
)
