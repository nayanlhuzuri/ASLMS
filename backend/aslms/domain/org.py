"""Group 1 — organisation and authentication: offices (hierarchy), users, OTPs, refresh tokens, preferences."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aslms.db.base import (
    Base,
    CreatedAtMixin,
    CreatedByMixin,
    MasterMixin,
    TableClass,
    TimestampMixin,
    pg_enum,
    ref_code,
    uuid_fk,
    uuid_pk,
)


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


class Office(TimestampMixin, MasterMixin, CreatedByMixin, Base):
    """Departments, directorates and other offices. `path` is the materialised code path
    (e.g. `EDU/EDU-DSE`) so a department's scope is `path LIKE 'EDU/%' OR path = 'EDU'`.
    Versioned (`valid_from` / `valid_to`) and deactivated, never deleted (DB_STANDARD §0)."""

    __tablename__ = "offices"
    __table_class__ = TableClass.MASTER

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    kind: Mapped[OfficeKind] = ref_code(OfficeKind, "ref_office_kind")
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("offices.id", ondelete="RESTRICT"), nullable=True
    )
    path: Mapped[str] = mapped_column(String(400), nullable=False, index=True)

    parent: Mapped[Office | None] = relationship(remote_side="Office.id")

    @property
    def department_code(self) -> str:
        return self.path.split("/", 1)[0]


class Designation(TimestampMixin, MasterMixin, CreatedByMixin, Base):
    """Organisation master of designations (Under Secretary, Section Officer, Standing Counsel…), so users
    and author snapshots draw on one list. `users.designation` keeps the text shown at write time."""

    __tablename__ = "designations"
    __table_class__ = TableClass.MASTER

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class User(TimestampMixin, CreatedByMixin, Base):
    __tablename__ = "users"
    __table_class__ = TableClass.MASTER

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    mobile: Mapped[str | None] = mapped_column(String(20))
    password_hash: Mapped[str] = mapped_column(String(300), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    designation: Mapped[str | None] = mapped_column(String(200))  # text as shown; the master row when known
    designation_id: Mapped[uuid.UUID | None] = uuid_fk(
        "designations.id", nullable=True, ondelete="RESTRICT", use_alter=True
    )
    office_id: Mapped[uuid.UUID] = uuid_fk("offices.id", ondelete="RESTRICT")
    role: Mapped[Role] = ref_code(Role, "ref_role")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    must_confirm_profile: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    office: Mapped[Office] = relationship(foreign_keys=[office_id])


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
