"""Group 8 — append-only events and audit log. No UPDATE or DELETE is ever issued against these tables, and
migration 0001 installs BEFORE UPDATE OR DELETE triggers (`aslms_forbid_change`) so the database refuses them."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, String, text
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from aslms.db.base import ActorSnapshotMixin, Base, CreatedAtMixin, pg_enum, uuid_fk, uuid_pk


class EventType(enum.StrEnum):
    # court record
    LISTED = "listed"
    LISTED_SUPPLEMENTARY = "listed_supplementary"
    NOT_LISTED_AS_EXPECTED = "not_listed_as_expected"
    HEARING_DATE_CHANGED = "hearing_date_changed"
    STATUS_CHANGED = "status_changed"
    ORDER_RECEIVED = "order_received"
    CASE_CREATED = "case_created"
    CASE_REFRESHED = "case_refreshed"
    CASE_MERGED = "case_merged"
    CASE_LINKED = "case_linked"
    # ownership
    RECOMMENDATION_MADE = "recommendation_made"
    RECOMMENDATION_DISMISSED = "recommendation_dismissed"
    CASE_CLAIMED = "case_claimed"
    OWNERSHIP_TRANSFER_REQUESTED = "ownership_transfer_requested"
    OWNERSHIP_TRANSFERRED = "ownership_transferred"
    OWNERSHIP_RELEASED = "ownership_released"
    WATCHER_ADDED = "watcher_added"
    # documents and dates
    DOCUMENT_UPLOADED = "document_uploaded"
    NEXT_DATE_EXTRACTED = "next_date_extracted"
    ALERT_RAISED = "alert_raised"
    # workflow (Phase 2)
    CUSTODY_MOVED = "custody_moved"
    REQUEST_SENT = "request_sent"
    REQUEST_ANSWERED = "request_answered"
    REQUEST_WITHDRAWN = "request_withdrawn"
    STAGE_CHANGED = "stage_changed"
    NOTE_ADDED = "note_added"
    FILE_ADDED = "file_added"
    DOCUMENT_INGESTED = "document_ingested"
    # operations
    SOURCE_FAILED = "source_failed"


class EventVisibility(enum.StrEnum):
    TRACKING_CARD = "tracking_card"  # visible to every signed-in user
    SCOPED = "scoped"  # visible within the case's scope only


class Event(CreatedAtMixin, Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_case_occurred", "case_id", text("occurred_at DESC")),
        Index("ix_events_type_occurred", "type", text("occurred_at DESC")),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID | None] = uuid_fk("cases.id", nullable=True, index=False)
    type: Mapped[EventType] = mapped_column(pg_enum(EventType, "event_type"), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = uuid_fk(
        "users.id", nullable=True, ondelete="SET NULL", index=False
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    dedupe_key: Mapped[str] = mapped_column(String(300), unique=True, nullable=False)
    visibility: Mapped[EventVisibility] = mapped_column(
        pg_enum(EventVisibility, "event_visibility"),
        nullable=False,
        server_default=EventVisibility.SCOPED.value,
    )


class AuditLog(CreatedAtMixin, ActorSnapshotMixin, Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_actor_created", "actor_user_id", text("created_at DESC")),
        Index("ix_audit_log_case_created", "case_id", text("created_at DESC")),
        Index("ix_audit_log_entity", "entity_type", "entity_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    case_id: Mapped[uuid.UUID | None] = uuid_fk("cases.id", nullable=True, ondelete="SET NULL", index=False)
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(400))
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
