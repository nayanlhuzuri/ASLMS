"""Declarative base, naming convention and the column helpers every model uses (docs/DB_STANDARD.md).

Every mapped class declares its table class (`__table_class__`, DB_STANDARD §0); the base writes it into the
table comment (`class=…`) so `COMMENT ON TABLE` in the migration and `\\dt+` in psql carry it."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import Any, ClassVar

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, MetaData, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
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
    """DB_STANDARD §0: who writes the table and how it is filled."""

    REFERENCE = "reference"  # ref_* code sets: seeded, labels editable
    MASTER = "master"  # organisation and court masters: administration or master_sync
    TRANSACTION = "transaction"  # the legal record: users, the daily cycle, the engine
    DERIVED = "derived"  # logs (INSERT-only) and regenerable rows


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {
        dict[str, Any]: JSONB,
        datetime: DateTime(timezone=True),
    }
    __table_class__: ClassVar[TableClass]

    def __init_subclass__(cls, **kw: Any) -> None:
        super().__init_subclass__(**kw)
        table = cls.__dict__.get("__table__")
        if table is None:  # abstract / mixin
            return
        tc = getattr(cls, "__table_class__", None)  # Base only annotates it; a mixin may set it
        if tc is None:
            raise TypeError(f"{cls.__name__}: declare __table_class__ (DB_STANDARD §0)")
        table.comment = f"class={TableClass(tc).value}"
        table.info["table_class"] = TableClass(tc)


def uuid_pk() -> Mapped[uuid.UUID]:
    """UUID v7 (RFC 9562), time-ordered: `uuid_generate_v7()` in the database, `uuid6.uuid7()` when the
    application needs the id before flush (DB_STANDARD §2)."""
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid7, server_default=text("uuid_generate_v7()")
    )


def uuid_fk(
    target: str, *, nullable: bool = False, ondelete: str = "RESTRICT", index: bool = True
) -> Mapped[Any]:
    """Foreign key; RESTRICT unless the referencing table is on the §6 cascade list."""
    return mapped_column(
        UUID(as_uuid=True), ForeignKey(target, ondelete=ondelete), nullable=nullable, index=index
    )


def pg_enum(cls: type[enum.Enum], name: str) -> Enum:
    """Postgres enum that stores the enum *values* (snake_case strings), not the member names."""
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


def ref_code(
    cls: type[enum.Enum], ref_table: str, *, nullable: bool = False, server_default: str | None = None
) -> Mapped[Any]:
    """A code-set column (DB_STANDARD §7): `varchar(40) REFERENCES ref_<set>(code)`. The Python enum stays the
    type in the ORM (its values are the codes), so services and tests are unchanged."""
    return mapped_column(
        Enum(
            cls,
            native_enum=False,
            length=40,
            create_constraint=False,
            values_callable=lambda e: [m.value for m in e],
        ),
        ForeignKey(f"{ref_table}.code", ondelete="RESTRICT"),
        nullable=nullable,
        server_default=server_default,
    )


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TimestampMixin(CreatedAtMixin):
    """`updated_at` is also maintained by the `set_updated_at()` trigger (§4), so direct SQL is covered."""

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ActorSnapshotMixin:
    """Who did it, frozen at write time (ground rule 5). The user row may change later; this does not."""

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_name: Mapped[str | None] = mapped_column(String(200))
    actor_designation: Mapped[str | None] = mapped_column(String(200))
    actor_office_code: Mapped[str | None] = mapped_column(String(64))


class CreatedByMixin:
    """§5: who created / last changed a master or transaction row that carries no actor snapshot.
    NULL for system writes (the daily cycle, the engine)."""

    @declared_attr
    def created_by(cls) -> Mapped[uuid.UUID | None]:
        return mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    @declared_attr
    def updated_by(cls) -> Mapped[uuid.UUID | None]:
        return mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class RefNoMixin:
    """§3: eOffice-style reference number `ASLMS/<OFFICE>/<TYPE>/<YYYY>/<NNNNNN>`, allocated once at insert by
    `services.refno.allocate_ref_no`, never changed."""

    ref_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)


class OptionalRefNoMixin:
    """§3 for tables where only some rows are quotable (uploads in `court_filing` / `internal`; manual next dates)."""

    ref_no: Mapped[str | None] = mapped_column(String(40), unique=True, nullable=True)


class DeactivateMixin:
    """§0 rule 4: masters are deactivated, never deleted."""

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MasterMixin(DeactivateMixin):
    """§0 rule 3: organisation masters (`offices`, `designations`) are versioned."""

    valid_from: Mapped[date] = mapped_column(Date, nullable=False, server_default=func.current_date())
    valid_to: Mapped[date | None] = mapped_column(Date)


CASCADE_TABLES: frozenset[str] = frozenset(
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
"""The only tables whose rows may go with their parent (DB_STANDARD §6). Gate step 4 checks this list."""
