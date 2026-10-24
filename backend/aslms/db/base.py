"""Declarative base and the column helpers every model uses (DB_STANDARD §0–§6).

- `uuid_pk()`      id uuid PRIMARY KEY DEFAULT uuid_generate_v7()      (§2)
- `uuid_fk()`      FK with ON DELETE RESTRICT by default               (§6)
- `ref_code()`     varchar(40) REFERENCES ref_<set>(code), typed as the Python enum (§7)
- `pg_enum()`      a native Postgres enum for machine states           (§7)
- mixins           created_at / updated_at, actor snapshot, created_by / updated_by, ref_no, master lifecycle
- `TableClass`     every model declares `__table_class__`; the class is written as COMMENT ON TABLE (§0)
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, MetaData, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column
from uuid6 import uuid7

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class TableClass(enum.StrEnum):
    REFERENCE = "reference"
    MASTER = "master"
    TRANSACTION = "transaction"
    DERIVED = "derived"


# FKs that may cascade (DB_STANDARD §6); everything else is RESTRICT.
CASCADE_TABLES = frozenset(
    {
        "otp_codes",
        "refresh_tokens",
        "user_notification_preferences",
        "notifications",
        "digests",
        "case_office_scores",
        "causelist_reconciliations",
        "document_text",
        "sourcetrace_ingestions",
        "assistant_messages",
        "napix_call_log",
    }
)

# Tables with an updated_at column; the migration adds the set_updated_at() trigger to each.
MUTABLE_TABLES: set[str] = set()
# Append-only tables (trigger aslms_forbid_change).
APPEND_ONLY_TABLES = (
    "events",
    "audit_log",
    "case_notes",
    "custody_history",
    "case_stages",
    "admin_ticket_documents",
    "membership_documents",
    "case_note_attachments",
    "sourcetrace_ingestions",  # design sourcetrace-connector, migration 0011
    "assistant_messages",  # design assistant, migration 0024
)
# Tables `aslms_app` may DELETE from although they belong to a case: unfinished drafts, not legal records
# (design custody-workflow, decisions 12-13; the owner's deviation from DB_STANDARD §6 / §9).
DRAFT_TABLES = ("case_note_drafts", "case_note_draft_documents")


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    __table_class__: TableClass

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        table = cls.__dict__.get("__table__")
        if table is None:
            table = getattr(cls, "__table__", None)
        if table is None:
            return
        table_class = getattr(cls, "__table_class__", None)
        if table_class is None:
            raise TypeError(f"{cls.__name__} must declare __table_class__ (DB_STANDARD §0)")
        table.comment = f"class={table_class.value}"
        if "updated_at" in table.c:
            MUTABLE_TABLES.add(table.name)


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid7, server_default=text("uuid_generate_v7()")
    )


def uuid_fk(
    target: str,
    *,
    nullable: bool = False,
    ondelete: str = "RESTRICT",
    index: bool = True,
    use_alter: bool = False,
) -> Mapped[uuid.UUID | None]:
    return mapped_column(
        UUID(as_uuid=True),
        ForeignKey(target, ondelete=ondelete, use_alter=use_alter),
        nullable=nullable,
        index=index,
    )


def pg_enum(cls: type[enum.Enum], name: str) -> Enum:
    """A native Postgres enum whose labels are the enum *values*."""
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e], create_type=True)


def ref_code(
    cls: type[enum.Enum], ref_table: str, *, nullable: bool = False, server_default: str | None = None
) -> Mapped[Any]:
    """A code-set column: varchar(40) with a FK to the ref_* table; the ORM type stays the Python enum."""
    kwargs: dict[str, Any] = {"nullable": nullable, "index": True}
    if server_default is not None:
        kwargs["server_default"] = server_default
    return mapped_column(
        Enum(
            cls,
            native_enum=False,
            length=40,
            create_constraint=False,
            values_callable=lambda e: [m.value for m in e],
        ),
        ForeignKey(f"{ref_table}.code", ondelete="RESTRICT"),
        **kwargs,
    )


def utcnow_sql() -> Any:
    return text("now()")


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class TimestampMixin(CreatedAtMixin):
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class ActorSnapshotMixin:
    """Who did it, frozen at write time (DB_STANDARD §5)."""

    @declared_attr
    def actor_user_id(cls) -> Mapped[uuid.UUID | None]:
        return mapped_column(
            UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL", use_alter=True), nullable=True
        )

    actor_name: Mapped[str | None] = mapped_column(String(200))
    actor_designation: Mapped[str | None] = mapped_column(String(200))
    actor_office_code: Mapped[str | None] = mapped_column(String(40))


class CreatedByMixin:
    @declared_attr
    def created_by(cls) -> Mapped[uuid.UUID | None]:
        return mapped_column(
            UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL", use_alter=True), nullable=True
        )

    @declared_attr
    def updated_by(cls) -> Mapped[uuid.UUID | None]:
        return mapped_column(
            UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL", use_alter=True), nullable=True
        )


class RefNoMixin:
    """ASLMS/<OFFICE>/<TYPE>/<YYYY>/<NNNNNN>, allocated once at insert (DB_STANDARD §3)."""

    ref_no: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)


class OptionalRefNoMixin:
    ref_no: Mapped[str | None] = mapped_column(String(40), nullable=True, unique=True)


class DeactivateMixin:
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MasterMixin(DeactivateMixin):
    """Versioned organisation master (DB_STANDARD §0 rule 3)."""

    valid_from: Mapped[date] = mapped_column(Date, nullable=False, server_default=text("current_date"))
    valid_to: Mapped[date | None] = mapped_column(Date)
