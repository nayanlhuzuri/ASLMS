"""Group 5 — ownership and matching: recommend and claim. The engine writes scores and recommendations; only an
explicit claim writes `case_ownership`."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from aslms.db.base import (
    ActorSnapshotMixin,
    Base,
    CreatedByMixin,
    DeactivateMixin,
    RefNoMixin,
    TableClass,
    TimestampMixin,
    pg_enum,
    uuid_fk,
    uuid_pk,
)


class CounselCode(TimestampMixin, DeactivateMixin, CreatedByMixin, Base):
    __tablename__ = "counsel_codes"
    __table_class__ = TableClass.MASTER
    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)  # as printed: "SC, EDU"
    office_id: Mapped[uuid.UUID] = uuid_fk("offices.id")
    weight: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False, server_default=text("0.950"))
    is_generic_state: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    notes: Mapped[str | None] = mapped_column(Text)


class PatternKind(enum.StrEnum):
    EXACT = "exact"
    PREFIX = "prefix"
    REGEX = "regex"


class OfficeNamePattern(TimestampMixin, DeactivateMixin, CreatedByMixin, Base):
    __tablename__ = "office_name_patterns"
    __table_class__ = TableClass.MASTER
    __table_args__ = (UniqueConstraint("office_id", "pattern", "kind"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    office_id: Mapped[uuid.UUID] = uuid_fk("offices.id")
    pattern: Mapped[str] = mapped_column(String(300), nullable=False)
    kind: Mapped[PatternKind] = mapped_column(pg_enum(PatternKind, "pattern_kind"), nullable=False)
    weight: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False, server_default=text("0.800"))


class OfficeKeyword(TimestampMixin, DeactivateMixin, CreatedByMixin, Base):
    __tablename__ = "office_keywords"
    __table_class__ = TableClass.MASTER
    __table_args__ = (UniqueConstraint("office_id", "keyword"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    office_id: Mapped[uuid.UUID] = uuid_fk("offices.id")
    keyword: Mapped[str] = mapped_column(String(200), nullable=False)
    weight: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False, server_default=text("0.400"))


class OfficeWatchlist(TimestampMixin, DeactivateMixin, ActorSnapshotMixin, Base):
    __tablename__ = "office_watchlist"
    __table_class__ = TableClass.MASTER
    __table_args__ = (UniqueConstraint("office_id", "cnr"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    office_id: Mapped[uuid.UUID] = uuid_fk("offices.id")
    cnr: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    case_id: Mapped[uuid.UUID | None] = uuid_fk("cases.id", nullable=True)
    reason: Mapped[str | None] = mapped_column(Text)
    weight: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False, server_default=text("0.750"))


class CaseOfficeScore(Base):
    """Recomputed by the engine; the one case-linked table that may cascade."""

    __tablename__ = "case_office_scores"
    __table_class__ = TableClass.DERIVED
    __table_args__ = (UniqueConstraint("case_id", "office_id"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = uuid_fk("cases.id", ondelete="CASCADE")
    office_id: Mapped[uuid.UUID] = uuid_fk("offices.id")
    score: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    signals: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    engine_version: Mapped[str] = mapped_column(String(20), nullable=False)


class ScoreBand(enum.StrEnum):
    HIGH = "high"  # >= 0.85
    MEDIUM = "medium"  # 0.50 – 0.85


class RecommendationStatus(enum.StrEnum):
    RECOMMENDED = "recommended"
    CLAIMED = "claimed"
    DISMISSED = "dismissed"
    SUGGESTED_ELSEWHERE = "suggested_elsewhere"
    EXPIRED = "expired"


class RecommendationOrigin(enum.StrEnum):
    CAUSE_LIST = "cause_list"
    RESCORE = "rescore"
    SEARCH = "search"
    SUGGESTION = "suggestion"
    WATCHLIST = "watchlist"


class Recommendation(TimestampMixin, ActorSnapshotMixin, Base):
    __tablename__ = "recommendations"
    __table_class__ = TableClass.TRANSACTION
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = uuid_fk("cases.id")
    office_id: Mapped[uuid.UUID] = uuid_fk("offices.id")
    score: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    band: Mapped[ScoreBand] = mapped_column(pg_enum(ScoreBand, "score_band"), nullable=False)
    status: Mapped[RecommendationStatus] = mapped_column(
        pg_enum(RecommendationStatus, "recommendation_status"),
        nullable=False,
        server_default="recommended",
        index=True,
    )
    origin: Mapped[RecommendationOrigin] = mapped_column(
        pg_enum(RecommendationOrigin, "recommendation_origin"), nullable=False, server_default="cause_list"
    )
    suggested_office_id: Mapped[uuid.UUID | None] = uuid_fk("offices.id", nullable=True)
    acted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(Text)


class OwnershipRole(enum.StrEnum):
    PRIMARY = "primary"
    WATCHER = "watcher"


class OwnershipStatus(enum.StrEnum):
    ACTIVE = "active"
    TRANSFERRED = "transferred"
    RELEASED = "released"


class CaseOwnership(TimestampMixin, ActorSnapshotMixin, Base):
    """Written only by an explicit claim (CLAUDE.md rule)."""

    __tablename__ = "case_ownership"
    __table_class__ = TableClass.TRANSACTION
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = uuid_fk("cases.id")
    office_id: Mapped[uuid.UUID] = uuid_fk("offices.id")
    role: Mapped[OwnershipRole] = mapped_column(
        pg_enum(OwnershipRole, "ownership_role"), nullable=False, server_default="primary"
    )
    officer_user_id: Mapped[uuid.UUID | None] = uuid_fk("users.id", nullable=True, ondelete="SET NULL")
    unit_office_id: Mapped[uuid.UUID | None] = uuid_fk("offices.id", nullable=True)
    claimed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    status: Mapped[OwnershipStatus] = mapped_column(
        pg_enum(OwnershipStatus, "ownership_status"), nullable=False, server_default="active", index=True
    )
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TransferStatus(enum.StrEnum):
    REQUESTED = "requested"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    WITHDRAWN = "withdrawn"


class OwnershipTransfer(TimestampMixin, RefNoMixin, ActorSnapshotMixin, Base):
    __tablename__ = "ownership_transfers"
    __table_class__ = TableClass.TRANSACTION
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = uuid_fk("cases.id")
    from_office_id: Mapped[uuid.UUID] = uuid_fk("offices.id")
    to_office_id: Mapped[uuid.UUID] = uuid_fk("offices.id")
    status: Mapped[TransferStatus] = mapped_column(
        pg_enum(TransferStatus, "transfer_status"), nullable=False, server_default="requested"
    )
    reason: Mapped[str | None] = mapped_column(Text)
    decided_by_user_id: Mapped[uuid.UUID | None] = uuid_fk("users.id", nullable=True, ondelete="SET NULL")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
