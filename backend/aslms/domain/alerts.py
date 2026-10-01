"""Group 7 — next dates, alerts, notifications and digests."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from aslms.db.base import (
    Base,
    CreatedAtMixin,
    CreatedByMixin,
    OptionalRefNoMixin,
    RefNoMixin,
    TableClass,
    TimestampMixin,
    pg_enum,
    ref_code,
    uuid_fk,
    uuid_pk,
)
from aslms.domain.org import Channel
from aslms.domain.reference import AlertKind


class NextDateSource(enum.StrEnum):
    CAUSELIST = "causelist"
    CURRENT_STATUS = "current_status"
    ORDER_SPECIFIC = "order_specific"
    ORDER_PERIOD = "order_period"
    MANUAL = "manual"


class ReviewStatus(enum.StrEnum):
    NOT_NEEDED = "not_needed"
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class NextDate(TimestampMixin, OptionalRefNoMixin, CreatedByMixin, Base):
    __tablename__ = "next_dates"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (
        UniqueConstraint("case_id", "next_date", "source", "order_id", postgresql_nulls_not_distinct=True),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = uuid_fk("cases.id")
    next_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    source: Mapped[NextDateSource] = mapped_column(
        pg_enum(NextDateSource, "next_date_source"), nullable=False
    )
    order_id: Mapped[uuid.UUID | None] = uuid_fk("orders.id", nullable=True)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False, server_default=text("1.000"))
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    review_status: Mapped[ReviewStatus] = mapped_column(
        pg_enum(ReviewStatus, "review_status"), nullable=False, server_default="not_needed"
    )
    reviewed_by_user_id: Mapped[uuid.UUID | None] = uuid_fk("users.id", nullable=True, ondelete="SET NULL")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)


class Severity(enum.StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"


class AlertStatus(enum.StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    DONE = "done"
    EXPIRED = "expired"


class Alert(TimestampMixin, RefNoMixin, Base):
    __tablename__ = "alerts"
    __table_class__ = TableClass.TRANSACTION
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = uuid_fk("cases.id")
    kind: Mapped[AlertKind] = ref_code(AlertKind, "ref_alert_kind")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    severity: Mapped[Severity] = mapped_column(
        pg_enum(Severity, "alert_severity"), nullable=False, server_default="normal"
    )
    status: Mapped[AlertStatus] = mapped_column(
        pg_enum(AlertStatus, "alert_status"), nullable=False, server_default="open", index=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    source_event_id: Mapped[uuid.UUID | None] = uuid_fk("events.id", nullable=True, use_alter=True)
    dedupe_key: Mapped[str] = mapped_column(String(300), nullable=False, unique=True)
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
    __table_class__ = TableClass.DERIVED
    id: Mapped[uuid.UUID] = uuid_pk()
    alert_id: Mapped[uuid.UUID] = uuid_fk("alerts.id", ondelete="CASCADE")
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id", ondelete="CASCADE")
    channel: Mapped[Channel] = mapped_column(pg_enum(Channel, "notification_channel"), nullable=False)
    status: Mapped[NotificationStatus] = mapped_column(
        pg_enum(NotificationStatus, "notification_status"), nullable=False, server_default="queued"
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    dedupe_key: Mapped[str] = mapped_column(String(300), nullable=False, unique=True)


class Digest(CreatedAtMixin, Base):
    __tablename__ = "digests"
    __table_class__ = TableClass.DERIVED
    __table_args__ = (UniqueConstraint("user_id", "digest_date"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id", ondelete="CASCADE")
    digest_date: Mapped[date] = mapped_column(Date, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    alert_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, server_default="{}"
    )
