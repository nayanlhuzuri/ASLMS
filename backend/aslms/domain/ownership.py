"""Group 5 — ownership and matching: recommend and claim. The engine writes scores and recommendations; only an
explicit claim writes `case_ownership`."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
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

WEIGHT_CHECK = "weight IS NULL OR (weight > 0 AND weight <= 1)"


class ScoringSettings(TimestampMixin, CreatedByMixin, Base):
    """The matching weights and band thresholds, versioned: a save inserts a new version and closes the
    previous one (design recommend-and-claim, decision 21). Values are never updated in place; rows are never
    deleted."""

    __tablename__ = "scoring_settings"
    __table_class__ = TableClass.MASTER
    __table_args__ = (
        CheckConstraint(
            "weight_counsel_code > 0 AND weight_counsel_code <= 1 AND "
            "weight_name_pattern > 0 AND weight_name_pattern <= 1 AND "
            "weight_watchlist > 0 AND weight_watchlist <= 1 AND "
            "weight_linked_case > 0 AND weight_linked_case <= 1 AND "
            "weight_keyword > 0 AND weight_keyword <= 1",
            name="weights",
        ),
        CheckConstraint(
            "threshold_possible > 0 AND threshold_possible < threshold_strong AND threshold_strong <= 1",
            name="thresholds",
        ),
        CheckConstraint("is_current = (valid_to IS NULL)", name="current"),
        Index("ix_scoring_settings_current", "is_current", unique=True, postgresql_where=text("is_current")),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    version: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    weight_counsel_code: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    weight_name_pattern: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    weight_watchlist: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    weight_linked_case: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    weight_keyword: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    threshold_strong: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    threshold_possible: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CounselCode(TimestampMixin, DeactivateMixin, CreatedByMixin, Base):
    __tablename__ = "counsel_codes"
    __table_class__ = TableClass.MASTER
    __table_args__ = (CheckConstraint(WEIGHT_CHECK, name="weight"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)  # as printed: "SC, EDU"
    office_id: Mapped[uuid.UUID] = uuid_fk("offices.id")
    weight: Mapped[float | None] = mapped_column(Numeric(4, 3))  # NULL = the kind's setting
    is_generic_state: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    notes: Mapped[str | None] = mapped_column(Text)


class PatternKind(enum.StrEnum):
    EXACT = "exact"
    PREFIX = "prefix"
    REGEX = "regex"


class OfficeNamePattern(TimestampMixin, DeactivateMixin, CreatedByMixin, Base):
    __tablename__ = "office_name_patterns"
    __table_class__ = TableClass.MASTER
    __table_args__ = (
        UniqueConstraint("office_id", "pattern", "kind"),
        CheckConstraint(WEIGHT_CHECK, name="weight"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    office_id: Mapped[uuid.UUID] = uuid_fk("offices.id")
    pattern: Mapped[str] = mapped_column(String(300), nullable=False)
    kind: Mapped[PatternKind] = mapped_column(pg_enum(PatternKind, "pattern_kind"), nullable=False)
    weight: Mapped[float | None] = mapped_column(Numeric(4, 3))


class OfficeKeyword(TimestampMixin, DeactivateMixin, CreatedByMixin, Base):
    __tablename__ = "office_keywords"
    __table_class__ = TableClass.MASTER
    __table_args__ = (UniqueConstraint("office_id", "keyword"), CheckConstraint(WEIGHT_CHECK, name="weight"))
    id: Mapped[uuid.UUID] = uuid_pk()
    office_id: Mapped[uuid.UUID] = uuid_fk("offices.id")
    keyword: Mapped[str] = mapped_column(String(200), nullable=False)
    weight: Mapped[float | None] = mapped_column(Numeric(4, 3))


class OfficeWatchlist(TimestampMixin, DeactivateMixin, ActorSnapshotMixin, Base):
    __tablename__ = "office_watchlist"
    __table_class__ = TableClass.MASTER
    __table_args__ = (UniqueConstraint("office_id", "cnr"), CheckConstraint(WEIGHT_CHECK, name="weight"))
    id: Mapped[uuid.UUID] = uuid_pk()
    office_id: Mapped[uuid.UUID] = uuid_fk("offices.id")
    cnr: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    case_id: Mapped[uuid.UUID | None] = uuid_fk("cases.id", nullable=True)
    reason: Mapped[str | None] = mapped_column(Text)
    weight: Mapped[float | None] = mapped_column(Numeric(4, 3))


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
    HIGH = "high"  # >= threshold_strong (default 0.85)
    MEDIUM = "medium"  # threshold_possible (default 0.50) up to threshold_strong


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
    __table_args__ = (
        CheckConstraint("score >= 0 AND score <= 1", name="score_range"),
        Index(
            "ix_recommendations_active",
            "case_id",
            "office_id",
            unique=True,
            postgresql_where=text("status = 'recommended'"),
        ),
    )
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
    """Written only by an explicit claim, an accepted transfer or a take-over (CLAUDE.md rule). A primary row
    is never released: a claimed case never returns to the pool."""

    __tablename__ = "case_ownership"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (
        CheckConstraint("status <> 'released' OR role = 'watcher'", name="release_watcher"),
        Index(
            "ix_case_ownership_active_primary",
            "case_id",
            unique=True,
            postgresql_where=text("status = 'active' AND role = 'primary'"),
        ),
        Index(
            "ix_case_ownership_active_office",
            "case_id",
            "office_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = uuid_fk("cases.id")
    office_id: Mapped[uuid.UUID] = uuid_fk("offices.id")
    role: Mapped[OwnershipRole] = mapped_column(
        pg_enum(OwnershipRole, "ownership_role"), nullable=False, server_default="primary"
    )
    officer_user_id: Mapped[uuid.UUID | None] = uuid_fk("users.id", nullable=True, ondelete="SET NULL")
    unit_office_id: Mapped[uuid.UUID | None] = uuid_fk("offices.id", nullable=True)
    allotted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    allotted_by_user_id: Mapped[uuid.UUID | None] = uuid_fk("users.id", nullable=True, ondelete="SET NULL")
    claimed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    status: Mapped[OwnershipStatus] = mapped_column(
        pg_enum(OwnershipStatus, "ownership_status"), nullable=False, server_default="active", index=True
    )
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    release_reason: Mapped[str | None] = mapped_column(Text)


class TransferStatus(enum.StrEnum):
    REQUESTED = "requested"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    WITHDRAWN = "withdrawn"


class OwnershipTransfer(TimestampMixin, RefNoMixin, ActorSnapshotMixin, Base):
    __tablename__ = "ownership_transfers"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (
        Index(
            "ix_ownership_transfers_open",
            "case_id",
            unique=True,
            postgresql_where=text("status = 'requested'"),
        ),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = uuid_fk("cases.id")
    from_office_id: Mapped[uuid.UUID] = uuid_fk("offices.id")
    to_office_id: Mapped[uuid.UUID] = uuid_fk("offices.id")
    status: Mapped[TransferStatus] = mapped_column(
        pg_enum(TransferStatus, "transfer_status"), nullable=False, server_default="requested"
    )
    reason: Mapped[str | None] = mapped_column(Text)
    stay_as_watcher: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    decision_note: Mapped[str | None] = mapped_column(Text)
    decided_by_user_id: Mapped[uuid.UUID | None] = uuid_fk("users.id", nullable=True, ondelete="SET NULL")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
