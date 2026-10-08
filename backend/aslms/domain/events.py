"""Group 8 — events and audit (append-only; the trigger `aslms_forbid_change` blocks UPDATE and DELETE)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from aslms.db.base import (
    ActorSnapshotMixin,
    Base,
    CreatedAtMixin,
    TableClass,
    pg_enum,
    ref_code,
    uuid_fk,
    uuid_pk,
)
from aslms.domain.reference import EventType


class EventVisibility(enum.StrEnum):
    TRACKING_CARD = "tracking_card"
    SCOPED = "scoped"


class Event(CreatedAtMixin, Base):
    __tablename__ = "events"
    __table_class__ = TableClass.DERIVED
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID | None] = uuid_fk("cases.id", nullable=True)
    type: Mapped[EventType] = ref_code(EventType, "ref_event_type")
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"), index=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = uuid_fk("users.id", nullable=True, ondelete="SET NULL")
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    dedupe_key: Mapped[str] = mapped_column(String(300), nullable=False, unique=True)
    visibility: Mapped[EventVisibility] = mapped_column(
        pg_enum(EventVisibility, "event_visibility"), nullable=False, server_default="scoped"
    )


class AuditLog(CreatedAtMixin, ActorSnapshotMixin, Base):
    __tablename__ = "audit_log"
    __table_class__ = TableClass.DERIVED
    # the audit search (design audit-screens, migration 0013): by time, and by actor then time
    __table_args__ = (
        Index("ix_audit_log_created_at", "created_at"),
        Index("ix_audit_log_actor_created", "actor_user_id", "created_at"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    case_id: Mapped[uuid.UUID | None] = uuid_fk("cases.id", nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(400))
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)
