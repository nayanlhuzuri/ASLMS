"""Group 7 — next dates, alerts, notifications and digests."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from aslms.db.base import Base, CreatedAtMixin, TimestampMixin, pg_enum, uuid_fk, uuid_pk
from aslms.domain.org import NOTIFICATION_CHANNEL, Channel


class NextDateSource(enum.StrEnum):
    CAUSELIST = "causelist"
    CURRENT_STATUS = "current_status"
    ORDER_SPECIFIC = "order_specific"  # a date printed in the order
    ORDER_PERIOD = "order_period"  # "list after two weeks", read by SourceTrace (Phase 2)
    MANUAL = "manual"


class ReviewStatus(enum.StrEnum):
    NONE = "none"
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class NextDate(TimestampMixin, Base):
    __tablename__ = "next_dates"
    __table_args__ = (
        UniqueConstraint("case_id", "next_date", "source", "order_id"),
        Index("ix_next_dates_next_date", "next_date"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = uuid_fk("cases.id")
    next_date: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[NextDateSource] = mapped_column(
        pg_enum(NextDateSource, "next_date_source"), nullable=False
    )
    order_id: Mapped[uuid.UUID | None] = uuid_fk("orders.id", nullable=True, ondelete="SET NULL")
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    review_status: Mapped[ReviewStatus] = mapped_column(
        pg_enum(ReviewStatus, "review_status"), nullable=False, server_default=ReviewStatus.NONE.value
    )
    reviewed_by_user_id: Mapped[uuid.UUID | None] = uuid_fk("users.id", nullable=True, ondelete="SET NULL")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)


class AlertKind(enum.StrEnum):
    HEARING = "hearing"
    NEXT_DATE = "next_date"
    COMPLIANCE = "compliance"
    ORDER_RECEIVED = "order_received"
    UNCLAIMED_FOLLOWUP = "unclaimed_followup"
    DATA_HEALTH = "data_health"


class Severity(enum.StrEnum):
    CRITICAL = "critical"  # within 48 hours
    HIGH = "high"  # this week
    NORMAL = "normal"


class AlertStatus(enum.StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    DONE = "done"
    EXPIRED = "expired"


class Alert(TimestampMixin, Base):
    __tablename__ = "alerts"
    __table_args__ = (Index("ix_alerts_due_status", "due_at", "status"), Index("ix_alerts_case", "case_id"))

    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID | None] = uuid_fk("cases.id", nullable=True, index=False)
    kind: Mapped[AlertKind] = mapped_column(pg_enum(AlertKind, "alert_kind"), nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    severity: Mapped[Severity] = mapped_column(
        pg_enum(Severity, "alert_severity"), nullable=False, server_default=Severity.NORMAL.value
    )
    status: Mapped[AlertStatus] = mapped_column(
        pg_enum(AlertStatus, "alert_status"), nullable=False, server_default=AlertStatus.OPEN.value
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    source_event_id: Mapped[uuid.UUID | None] = uuid_fk("events.id", nullable=True, ondelete="SET NULL")
    dedupe_key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    acknowledged_by_user_id: Mapped[uuid.UUID | None] = uuid_fk(
        "users.id", nullable=True, ondelete="SET NULL"
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NotificationStatus(enum.StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"
    READ = "read"


class Notification(CreatedAtMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_status", "user_id", "status"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    alert_id: Mapped[uuid.UUID | None] = uuid_fk("alerts.id", nullable=True)
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id", index=False)
    channel: Mapped[Channel] = mapped_column(NOTIFICATION_CHANNEL, nullable=False)
    status: Mapped[NotificationStatus] = mapped_column(
        pg_enum(NotificationStatus, "notification_status"),
        nullable=False,
        server_default=NotificationStatus.QUEUED.value,
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    dedupe_key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)


class Digest(CreatedAtMixin, Base):
    __tablename__ = "digests"
    __table_args__ = (UniqueConstraint("user_id", "digest_date"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id")
    digest_date: Mapped[date] = mapped_column(Date, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    alert_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, server_default="{}"
    )
