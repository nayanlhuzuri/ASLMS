"""Group 1 — organisation and authentication."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aslms.db.base import (
    ActorSnapshotMixin,
    Base,
    CreatedByMixin,
    MasterMixin,
    TableClass,
    TimestampMixin,
    pg_enum,
    ref_code,
    uuid_fk,
    uuid_pk,
)
from aslms.domain.reference import OfficeKind, Permission, Role


class Office(TimestampMixin, MasterMixin, CreatedByMixin, Base):
    __tablename__ = "offices"
    __table_class__ = TableClass.MASTER
    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[OfficeKind] = ref_code(OfficeKind, "ref_office_kind")
    parent_id: Mapped[uuid.UUID | None] = uuid_fk("offices.id", nullable=True)
    path: Mapped[str] = mapped_column(String(400), nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text)

    parent = relationship("Office", remote_side="Office.id", foreign_keys=[parent_id])


class Designation(TimestampMixin, MasterMixin, CreatedByMixin, Base):
    __tablename__ = "designations"
    __table_class__ = TableClass.MASTER
    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))


class User(TimestampMixin, MasterMixin, CreatedByMixin, Base):
    __tablename__ = "users"
    __table_class__ = TableClass.MASTER
    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True)
    mobile: Mapped[str | None] = mapped_column(String(20))
    password_hash: Mapped[str] = mapped_column(String(300), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    designation: Mapped[str | None] = mapped_column(String(200))
    designation_id: Mapped[uuid.UUID | None] = uuid_fk("designations.id", nullable=True, use_alter=True)
    office_id: Mapped[uuid.UUID] = uuid_fk("offices.id")
    role: Mapped[Role] = ref_code(Role, "ref_role")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    must_confirm_profile: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    office = relationship("Office", foreign_keys=[office_id])


class RolePermission(TimestampMixin, CreatedByMixin, Base):
    """The type matrix: which functions a user type has. One row per (type, function); `is_enabled` is what
    the super admin switches (`access.manage_types`). Seeded from the plan's Table 1."""

    __tablename__ = "role_permissions"
    __table_class__ = TableClass.MASTER
    __table_args__ = (UniqueConstraint("role", "permission"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    role: Mapped[Role] = ref_code(Role, "ref_role")
    permission: Mapped[Permission] = ref_code(Permission, "ref_permission")
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class PermissionEffect(enum.StrEnum):
    GRANT = "grant"
    DENY = "deny"


class UserPermission(TimestampMixin, MasterMixin, ActorSnapshotMixin, Base):
    """A per-user override on top of the type matrix: a function granted that the type lacks, or one denied
    that the type has. `granted_by_user_id` and the actor snapshot say who; `valid_to` / `is_active` end it
    (rows are never deleted)."""

    __tablename__ = "user_permissions"
    __table_class__ = TableClass.MASTER
    __table_args__ = (UniqueConstraint("user_id", "permission"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id")
    permission: Mapped[Permission] = ref_code(Permission, "ref_permission")
    effect: Mapped[PermissionEffect] = mapped_column(
        pg_enum(PermissionEffect, "permission_effect"), nullable=False, server_default="grant"
    )
    granted_by_user_id: Mapped[uuid.UUID | None] = uuid_fk("users.id", nullable=True, ondelete="SET NULL")
    reason: Mapped[str | None] = mapped_column(Text)


class OtpPurpose(enum.StrEnum):
    LOGIN = "login"
    PASSWORD_RESET = "password_reset"
    NEW_DEVICE = "new_device"


class OtpCode(Base):
    __tablename__ = "otp_codes"
    __table_class__ = TableClass.DERIVED
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id", ondelete="CASCADE")
    purpose: Mapped[OtpPurpose] = mapped_column(pg_enum(OtpPurpose, "otp_purpose"), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(300), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    __table_class__ = TableClass.DERIVED
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id", ondelete="CASCADE")
    token_hash: Mapped[str] = mapped_column(String(300), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    device_label: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Channel(enum.StrEnum):
    IN_APP = "in_app"
    EMAIL = "email"
    SMS = "sms"


class DigestMode(enum.StrEnum):
    NONE = "none"
    DAILY = "daily"


class UserNotificationPreference(TimestampMixin, Base):
    __tablename__ = "user_notification_preferences"
    __table_class__ = TableClass.MASTER
    __table_args__ = (UniqueConstraint("user_id", "channel"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id", ondelete="CASCADE")
    channel: Mapped[Channel] = mapped_column(pg_enum(Channel, "notification_channel"), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    digest: Mapped[DigestMode] = mapped_column(
        pg_enum(DigestMode, "digest_mode"), nullable=False, server_default="none"
    )
    critical_only: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


__all__ = [
    "Channel",
    "PermissionEffect",
    "RolePermission",
    "UserPermission",
    "Designation",
    "DigestMode",
    "Office",
    "OtpCode",
    "OtpPurpose",
    "RefreshToken",
    "User",
    "UserNotificationPreference",
    "UUID",
]
