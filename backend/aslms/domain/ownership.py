"""Group 5 — ownership and matching: signals configured per office, per-case scores, recommendations,
claims (ownership) and transfers. Nothing here is written automatically except scores and recommendations;
`case_ownership` rows exist only because a department claimed."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Index, Numeric, String, Text, UniqueConstraint, text
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
    """Standing-counsel code as printed in the cause list advocate column (e.g. `SC, EDU`) → office.
    `is_generic_state` marks codes such as `PP, ASSAM` that identify the State but not a department."""

    __tablename__ = "counsel_codes"
    __table_class__ = TableClass.MASTER

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    office_id: Mapped[uuid.UUID] = uuid_fk("offices.id", ondelete="RESTRICT")
    weight: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False, server_default="0.950")
    is_generic_state: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    notes: Mapped[str | None] = mapped_column(Text)


class PatternKind(enum.StrEnum):
    EXACT = "exact"
    PREFIX = "prefix"
    REGEX = "regex"


class OfficeNamePattern(TimestampMixin, DeactivateMixin, CreatedByMixin, Base):
    __tablename__ = "office_name_patterns"
    __table_class__ = TableClass.MASTER
    __table_args__ = (UniqueConstraint("office_id", "pattern"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    office_id: Mapped[uuid.UUID] = uuid_fk("offices.id")
    pattern: Mapped[str] = mapped_column(String(300), nullable=False)
    kind: Mapped[PatternKind] = mapped_column(pg_enum(PatternKind, "pattern_kind"), nullable=False)
    weight: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False, server_default="0.800")


class OfficeKeyword(TimestampMixin, DeactivateMixin, CreatedByMixin, Base):
    __tablename__ = "office_keywords"
    __table_class__ = TableClass.MASTER
    __table_args__ = (UniqueConstraint("office_id", "keyword"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    office_id: Mapped[uuid.UUID] = uuid_fk("offices.id")
    keyword: Mapped[str] = mapped_column(String(200), nullable=False)
    weight: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False, server_default="0.400")


class OfficeWatchlist(TimestampMixin, DeactivateMixin, ActorSnapshotMixin, Base):
    __tablename__ = "office_watchlist"
    __table_class__ = TableClass.MASTER
    __table_args__ = (UniqueConstraint("office_id", "cnr"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    office_id: Mapped[uuid.UUID] = uuid_fk("offices.id")
    cnr: Mapped[str] = mapped_column(String(16), nullable=False)
    case_id: Mapped[uuid.UUID | None] = uuid_fk("cases.id", nullable=True, ondelete="RESTRICT")
    reason: Mapped[str | None] = mapped_column(Text)
    weight: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False, server_default="0.750")


class CaseOfficeScore(TimestampMixin, Base):
    """Latest score per (case, office). `signals` is a list of {kind, value, weight, matched_text}."""

    __tablename__ = "case_office_scores"
    __table_class__ = TableClass.DERIVED
    __table_args__ = (
        UniqueConstraint("case_id", "office_id"),
        Index("ix_case_office_scores_office_score", "office_id", "score"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = uuid_fk("cases.id", ondelete="CASCADE")  # §6: recomputed
    office_id: Mapped[uuid.UUID] = uuid_fk("offices.id")
    score: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    signals: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, server_default="[]")
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(32), nullable=False)


class ScoreBand(enum.StrEnum):
    HIGH = "high"  # ≥ 0.85
    MEDIUM = "medium"  # 0.50 – 0.85


class RecommendationStatus(enum.StrEnum):
    RECOMMENDED = "recommended"
    CLAIMED = "claimed"
    DISMISSED = "dismissed"
    SUGGESTED_ELSEWHERE = "suggested_elsewhere"
    EXPIRED = "expired"


class RecommendationOrigin(enum.StrEnum):
    CAUSE_LIST = "cause_list"
    DISCOVERY = "discovery"
    SUGGESTION = "suggestion"
    LINK_HISTORY = "link_history"
    SEARCH = "search"


class Recommendation(TimestampMixin, ActorSnapshotMixin, Base):
    """What the inbox shows. Cases scoring below the possible threshold get no row and form the
    unclaimed pool (cases with no active ownership)."""

    __tablename__ = "recommendations"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (
        Index(
            "uq_recommendations_active",
            "case_id",
            "office_id",
            unique=True,
            postgresql_where=text("status = 'recommended'"),
        ),
        Index("ix_recommendations_office_status", "office_id", "status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = uuid_fk("cases.id")
    office_id: Mapped[uuid.UUID] = uuid_fk("offices.id")
    score: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    band: Mapped[ScoreBand] = mapped_column(pg_enum(ScoreBand, "score_band"), nullable=False)
    status: Mapped[RecommendationStatus] = mapped_column(
        pg_enum(RecommendationStatus, "recommendation_status"),
        nullable=False,
        server_default=RecommendationStatus.RECOMMENDED.value,
    )
    origin: Mapped[RecommendationOrigin] = mapped_column(
        pg_enum(RecommendationOrigin, "recommendation_origin"), nullable=False
    )
    suggested_office_id: Mapped[uuid.UUID | None] = uuid_fk("offices.id", nullable=True, ondelete="SET NULL")
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
    """Written only by an explicit claim (or accepted transfer). One active primary owner per case."""

    __tablename__ = "case_ownership"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (
        Index(
            "uq_case_ownership_one_primary",
            "case_id",
            unique=True,
            postgresql_where=text("role = 'primary' AND status = 'active'"),
        ),
        Index(
            "uq_case_ownership_active_office",
            "case_id",
            "office_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index("ix_case_ownership_office_status", "office_id", "status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = uuid_fk("cases.id")
    office_id: Mapped[uuid.UUID] = uuid_fk("offices.id", ondelete="RESTRICT")
    role: Mapped[OwnershipRole] = mapped_column(pg_enum(OwnershipRole, "ownership_role"), nullable=False)
    officer_user_id: Mapped[uuid.UUID | None] = uuid_fk("users.id", nullable=True, ondelete="SET NULL")
    # the directorate / section inside the department the case is allotted to (migration 0002)
    unit_office_id: Mapped[uuid.UUID | None] = uuid_fk("offices.id", nullable=True, ondelete="SET NULL")
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[OwnershipStatus] = mapped_column(
        pg_enum(OwnershipStatus, "ownership_status"),
        nullable=False,
        server_default=OwnershipStatus.ACTIVE.value,
    )
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TransferStatus(enum.StrEnum):
    REQUESTED = "requested"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    WITHDRAWN = "withdrawn"


class OwnershipTransfer(TimestampMixin, RefNoMixin, ActorSnapshotMixin, Base):
    """`ref_no` = `ASLMS/<from department>/TRF/YYYY/NNNNNN`."""

    __tablename__ = "ownership_transfers"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (Index("ix_ownership_transfers_to_office_status", "to_office_id", "status"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = uuid_fk("cases.id")
    from_office_id: Mapped[uuid.UUID] = uuid_fk("offices.id", ondelete="RESTRICT")
    to_office_id: Mapped[uuid.UUID] = uuid_fk("offices.id", ondelete="RESTRICT")
    status: Mapped[TransferStatus] = mapped_column(
        pg_enum(TransferStatus, "transfer_status"),
        nullable=False,
        server_default=TransferStatus.REQUESTED.value,
    )
    reason: Mapped[str | None] = mapped_column(Text)
    decided_by_user_id: Mapped[uuid.UUID | None] = uuid_fk("users.id", nullable=True, ondelete="SET NULL")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
