"""Group 1 — organisation and authentication."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    CHAR,
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
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
    """A login (design `user-memberships`, decision 1). `office_id`, `role`, `designation` and `designation_id`
    mirror the primary membership: written only by `services/memberships.py`, never read for authorisation.
    Design `office-head-picker`, decision 16: `office_id` and `role` are NULL together only for a login created
    with no office yet, until its first membership writes the mirror (never back to NULL)."""

    __tablename__ = "users"
    __table_class__ = TableClass.MASTER
    __table_args__ = (CheckConstraint("(office_id IS NULL) = (role IS NULL)", name="placed"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True)
    mobile: Mapped[str | None] = mapped_column(String(20))
    password_hash: Mapped[str] = mapped_column(String(300), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    designation: Mapped[str | None] = mapped_column(String(200))
    designation_id: Mapped[uuid.UUID | None] = uuid_fk("designations.id", nullable=True, use_alter=True)
    office_id: Mapped[uuid.UUID | None] = uuid_fk("offices.id", nullable=True)
    role: Mapped[Role | None] = ref_code(Role, "ref_role", nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    must_confirm_profile: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # design `otp-and-profile` (migration 0010): access tokens issued before `password_changed_at` are refused;
    # `must_change_password` is set when someone else set the password; `profile_confirmed_at` the first confirm
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    profile_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    office = relationship("Office", foreign_keys=[office_id])


class UserMembership(TimestampMixin, MasterMixin, CreatedByMixin, Base):
    """One office a person serves in, with that office's designation and user type (design `user-memberships`,
    decisions 1-3, 13-15). The unit of authority: functions, scope and visibility are computed per membership.
    `department_id` is the Department-tier ancestor of the office (NULL at the State tier), derived at insert and
    never changed. At most one active membership per person per department, one primary per login, one active
    super admin in the system, one active department admin and one active head per department. Ended, never
    deleted."""

    __tablename__ = "user_memberships"
    __table_class__ = TableClass.MASTER
    __table_args__ = (
        Index(
            "ix_user_memberships_one_per_department",
            "user_id",
            "department_id",
            unique=True,
            postgresql_where=text("is_active"),
            postgresql_nulls_not_distinct=True,
        ),
        Index(
            "ix_user_memberships_primary",
            "user_id",
            unique=True,
            postgresql_where=text("is_primary AND is_active"),
        ),
        Index(
            "ix_user_memberships_one_super_admin",
            "role",
            unique=True,
            postgresql_where=text("role = 'super_admin' AND is_active"),
        ),
        Index(
            "ix_user_memberships_one_dept_admin",
            "department_id",
            unique=True,
            postgresql_where=text("role = 'dept_admin' AND is_active"),
        ),
        Index(
            "ix_user_memberships_one_dept_head",
            "department_id",
            unique=True,
            postgresql_where=text("role = 'dept_head' AND is_active"),
        ),
        Index("ix_user_memberships_office_active", "office_id", postgresql_where=text("is_active")),
        CheckConstraint("is_active = (deactivated_at IS NULL)", name="active"),
        CheckConstraint("NOT is_primary OR is_active", name="primary_active"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id")
    office_id: Mapped[uuid.UUID] = uuid_fk("offices.id")
    department_id: Mapped[uuid.UUID | None] = uuid_fk("offices.id", nullable=True)
    role: Mapped[Role] = ref_code(Role, "ref_role")
    designation: Mapped[str | None] = mapped_column(String(200))
    designation_id: Mapped[uuid.UUID | None] = uuid_fk("designations.id", nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    end_reason: Mapped[str | None] = mapped_column(String(500))


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
    """A per-membership override on top of the type matrix (design `user-memberships`, decision 9): a function
    granted that the type lacks, or one denied that the type has. `user_id` equals the membership's user.
    `granted_by_user_id` and the actor snapshot say who; `valid_to` / `is_active` end it (never deleted)."""

    __tablename__ = "user_permissions"
    __table_class__ = TableClass.MASTER
    __table_args__ = (UniqueConstraint("membership_id", "permission"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id")
    membership_id: Mapped[uuid.UUID] = uuid_fk("user_memberships.id")
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
    """A one-time code; the `id` is the challenge id (design `otp-and-profile`, decision 2). `code_hash` is the
    HMAC-SHA256 of the code keyed with `ASLMS_JWT_SECRET`."""

    __tablename__ = "otp_codes"
    __table_class__ = TableClass.DERIVED
    __table_args__ = (Index("ix_otp_codes_user_purpose_created", "user_id", "purpose", "created_at"),)
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
    device_id: Mapped[uuid.UUID | None] = uuid_fk("user_devices.id", nullable=True)
    # the sign-in session (design session-timeout, decision 1); NULL for tokens issued before migration 0031
    session_id: Mapped[uuid.UUID | None] = uuid_fk("user_sessions.id", nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class UserDevice(TimestampMixin, Base):
    """A client a login signed in from (design `otp-and-profile`, decision 6): the device token is held by the
    client and stored here as its SHA-256. A code is still asked at every sign-in; the record drives the
    new-device notice and `/me/devices`. Written only by `services/auth.py`; never deleted."""

    __tablename__ = "user_devices"
    __table_class__ = TableClass.DERIVED
    __table_args__ = (CheckConstraint("last_seen_at >= first_seen_at", name="seen"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id")
    token_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False, unique=True)
    label: Mapped[str | None] = mapped_column(String(200))
    user_agent: Mapped[str | None] = mapped_column(String(400))
    first_ip: Mapped[str | None] = mapped_column(String(64))
    last_ip: Mapped[str | None] = mapped_column(String(64))
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SessionEndReason(enum.StrEnum):
    """Why a sign-in session ended (design `session-timeout`, decision 11)."""

    SIGNED_OUT = "signed_out"
    IDLE = "idle"
    LIMIT = "limit"
    REPLACED = "replaced"
    ENDED = "ended"


class UserSession(TimestampMixin, Base):
    """One row per sign-in (design `session-timeout`, decision 1): opened by the e-mailed-code step, never by a
    refresh. `expires_at` is the hard limit fixed at sign-in; `last_activity_at` moves only with `POST /me/activity`.
    Every authenticated request checks the row; idle and limit ends are written by the sweep. Written only by
    `services/sessions.py` and `services/auth.py`; never deleted."""

    __tablename__ = "user_sessions"
    __table_class__ = TableClass.DERIVED
    __table_args__ = (
        CheckConstraint("expires_at > started_at AND last_activity_at >= started_at", name="times"),
        CheckConstraint("(ended_at IS NULL) = (end_reason IS NULL)", name="ended"),
        Index("ix_user_sessions_open", "last_activity_at", postgresql_where=text("ended_at IS NULL")),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id")
    device_id: Mapped[uuid.UUID] = uuid_fk("user_devices.id")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_reason: Mapped[SessionEndReason | None] = mapped_column(
        pg_enum(SessionEndReason, "session_end_reason"), nullable=True
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
    "SessionEndReason",
    "UserDevice",
    "UserSession",
    "UserMembership",
    "UserNotificationPreference",
    "UUID",
]
