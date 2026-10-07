"""Group 1 (continued) — admin tickets: requests that need the super admin's decision, and the documents that
support them (design `user-memberships`, decisions 17-20)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from aslms.db.base import (
    ActorSnapshotMixin,
    Base,
    CreatedAtMixin,
    RefNoMixin,
    TableClass,
    TimestampMixin,
    pg_enum,
    ref_code,
    uuid_fk,
    uuid_pk,
)
from aslms.domain.reference import TicketKind


class TicketStatus(enum.StrEnum):
    OPEN = "open"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class AdminTicket(TimestampMixin, RefNoMixin, ActorSnapshotMixin, Base):
    """One request needing the super admin's decision. `open` → `approved` | `rejected` | `withdrawn` (final; the
    trigger `admin_tickets_closed_frozen` refuses any update of a closed row). The actor snapshot is the
    requesting membership; `payload` is the proposed change (validated by the kind's handler) and `result` what
    approval applied. Written only by `services/tickets.py`; never deleted."""

    __tablename__ = "admin_tickets"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (
        CheckConstraint("(status = 'open') = (decided_at IS NULL)", name="decided"),
        CheckConstraint("status <> 'rejected' OR decision_remark IS NOT NULL", name="reject_remark"),
        CheckConstraint("kind <> 'head_change' OR department_id IS NOT NULL", name="head_change"),
        Index(
            "ix_admin_tickets_one_open_head_change",
            "department_id",
            unique=True,
            postgresql_where=text("kind = 'head_change' AND status = 'open'"),
        ),
        Index("ix_admin_tickets_status_created", "status", "created_at"),
        Index("ix_admin_tickets_department_status", "department_id", "status"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    kind: Mapped[TicketKind] = ref_code(TicketKind, "ref_ticket_kind")
    status: Mapped[TicketStatus] = mapped_column(
        pg_enum(TicketStatus, "ticket_status"), nullable=False, server_default="open"
    )
    department_id: Mapped[uuid.UUID | None] = uuid_fk("offices.id", nullable=True)
    target_user_id: Mapped[uuid.UUID | None] = uuid_fk("users.id", nullable=True)
    target_membership_id: Mapped[uuid.UUID | None] = uuid_fk("user_memberships.id", nullable=True)
    requested_by_user_id: Mapped[uuid.UUID] = uuid_fk("users.id")
    requested_by_membership_id: Mapped[uuid.UUID] = uuid_fk("user_memberships.id")
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    request_remark: Mapped[str | None] = mapped_column(String(2000))
    result: Mapped[dict | None] = mapped_column(JSONB)
    decision_remark: Mapped[str | None] = mapped_column(String(2000))
    decided_by_user_id: Mapped[uuid.UUID | None] = uuid_fk("users.id", nullable=True, ondelete="SET NULL")
    decided_by_name: Mapped[str | None] = mapped_column(String(200))
    decided_by_designation: Mapped[str | None] = mapped_column(String(200))
    decided_by_office_code: Mapped[str | None] = mapped_column(String(40))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AdminTicketDocument(CreatedAtMixin, ActorSnapshotMixin, Base):
    """A supporting document (kind `admin`) attached to a ticket. Append-only."""

    __tablename__ = "admin_ticket_documents"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (UniqueConstraint("ticket_id", "document_id"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    ticket_id: Mapped[uuid.UUID] = uuid_fk("admin_tickets.id")
    document_id: Mapped[uuid.UUID] = uuid_fk("documents.id")


class MembershipDocument(CreatedAtMixin, ActorSnapshotMixin, Base):
    """The order that authorised a membership's change, linked on approval so it stays findable after the
    ticket is history. Append-only."""

    __tablename__ = "membership_documents"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (UniqueConstraint("membership_id", "document_id"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    membership_id: Mapped[uuid.UUID] = uuid_fk("user_memberships.id")
    document_id: Mapped[uuid.UUID] = uuid_fk("documents.id")
    ticket_id: Mapped[uuid.UUID | None] = uuid_fk("admin_tickets.id", nullable=True)
