"""Group 1 — organisation and authentication: offices (hierarchy), users, OTPs, refresh tokens, preferences."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aslms.db.base import Base, CreatedAtMixin, TableClass, TimestampMixin, pg_enum, uuid_fk, uuid_pk


class OfficeKind(enum.StrEnum):
    DEPARTMENT = "department"
    DIRECTORATE = "directorate"
    SECTION = "section"
    STATE_OFFICE = "state_office"  # CM / Chief Secretary office
    COUNSEL_OFFICE = "counsel_office"  # Standing Counsel / Advocate General
    CENTRAL_CELL = "central_cell"  # central monitoring cell


class Role(enum.StrEnum):
    STATE_OVERSIGHT = "state_oversight"
    DEPT_HEAD = "dept_head"
    DEPT_ADMIN = "dept_admin"
    DEPT_OFFICER = "dept_officer"
    DIRECTORATE_USER = "directorate_user"
    REFERRAL_REVIEWER = "referral_reviewer"
    STANDING_COUNSEL = "standing_counsel"
    CENTRAL_OPERATOR = "central_operator"
    AUDITOR = "auditor"


STATE_TIER_ROLES = frozenset({Role.STATE_OVERSIGHT, Role.AUDITOR, Role.CENTRAL_OPERATOR})


class Office(TimestampMixin, Base):
    """Departments, directorates and other offices. `path` is the materialised code path
    (e.g. `EDU/EDU-DSE`) so a department's scope is `path LIKE 'EDU/%' OR path = 'EDU'`."""

    __tablename__ = "offices"
    __table_class__ = TableClass.MASTER

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    kind: Mapped[OfficeKind] = mapped_column(pg_enum(OfficeKind, "office_kind"), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("offices.id", ondelete="RESTRICT"), nullable=True
    )
    path: Mapped[str] = mapped_column(String(400), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    parent: Mapped[Office | None] = relationship(remote_side="Office.id")

    @property
    def department_code(self) -> str:
        return self.path.split("/", 1)[0]


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_class__ = TableClass.MASTER

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    mobile: Mapped[str | None] = mapped_column(String(20))
    password_hash: Mapped[str] = mapped_column(String(300), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    designation: Mapped[str | None] = mapped_column(String(200))
    office_id: Mapped[uuid.UUID] = uuid_fk("offices.id", ondelete="RESTRICT")
    role: Mapped[Role] = mapped_column(pg_enum(Role, "user_role"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    must_confirm_profile: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    office: Mapped[Office] = relationship()


class OtpPurpose(enum.StrEnum):
    LOGIN = "login"
    PASSWORD_RESET = "password_reset"
    NEW_DEVICE = "new_device"


class OtpCode(CreatedAtMixin, Base):
    __tablename__ = "otp_codes"
    __table_class__ = TableClass.DERIVED
    __table_args__ = (Index("ix_otp_codes_user_purpose", "user_id", "purpose"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id", ondelete="CASCADE")
    purpose: Mapped[OtpPurpose] = mapped_column(pg_enum(OtpPurpose, "otp_purpose"), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RefreshToken(CreatedAtMixin, Base):
    __tablename__ = "refresh_tokens"
    __table_class__ = TableClass.DERIVED

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id", ondelete="CASCADE")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    device_label: Mapped[str | None] = mapped_column(String(200))


class Channel(enum.StrEnum):
    IN_APP = "in_app"
    EMAIL = "email"
    SMS = "sms"


NOTIFICATION_CHANNEL = pg_enum(Channel, "notification_channel")  # shared by preferences and notifications


class DigestMode(enum.StrEnum):
    NONE = "none"
    DAILY = "daily"


class UserNotificationPreference(TimestampMixin, Base):
    __tablename__ = "user_notification_preferences"
    __table_class__ = TableClass.MASTER
    __table_args__ = (UniqueConstraint("user_id", "channel"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id", ondelete="CASCADE")
    channel: Mapped[Channel] = mapped_column(NOTIFICATION_CHANNEL, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    digest: Mapped[DigestMode] = mapped_column(
        pg_enum(DigestMode, "digest_mode"), nullable=False, server_default=DigestMode.NONE.value
    )
    critical_only: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
