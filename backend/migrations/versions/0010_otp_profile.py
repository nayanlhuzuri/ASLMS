"""0010 otp and profile: e-mailed sign-in codes, devices, the first-sign-in flags

Design `otp-and-profile` (docs/schema/schema.md Group 1, "Data"):
1. `users.password_changed_at` (access tokens issued before it are refused), `users.must_change_password`
   (back-filled from `must_confirm_profile`: every login nobody has confirmed yet was given its password by
   someone else), `users.profile_confirmed_at`.
2. `user_devices` (derived): one row per client a login signed in from, the device token stored as its SHA-256;
   CHECK `ck_user_devices_seen`; `set_updated_at` trigger; `aslms_app` SELECT / INSERT / UPDATE (never deleted).
3. `refresh_tokens.device_id` (→ user_devices RESTRICT, NULL for tokens issued before this revision).
4. `ix_otp_codes_user_purpose_created` for the resend wait and the hourly cap.
No enum value, `ref_*` code or permission is added (`otp_purpose` already has the three purposes). The
downgrade stops while any `user_devices` row exists (a populated database is not silently stripped); otherwise
it drops exactly what this revision added.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. users
    op.add_column("users", sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "users",
        sa.Column("must_change_password", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("users", sa.Column("profile_confirmed_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE users SET must_change_password = must_confirm_profile WHERE must_confirm_profile")

    # 2. user_devices
    op.create_table(
        "user_devices",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.Column("user_agent", sa.String(length=400), nullable=True),
        sa.Column("first_ip", sa.String(length=64), nullable=True),
        sa.Column("last_ip", sa.String(length=64), nullable=True),
        sa.Column(
            "first_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("last_seen_at >= first_seen_at", name=op.f("ck_user_devices_seen")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_user_devices_user_id_users"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_devices")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_user_devices_token_hash")),
        comment="class=derived",
    )
    op.create_index(op.f("ix_user_devices_user_id"), "user_devices", ["user_id"], unique=False)
    op.execute(
        "CREATE TRIGGER user_devices_updated_at BEFORE UPDATE ON user_devices "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )
    op.execute("GRANT ALL ON user_devices TO aslms_owner")
    op.execute("GRANT SELECT ON user_devices TO aslms_readonly")
    op.execute("GRANT SELECT, INSERT, UPDATE ON user_devices TO aslms_app")

    # 3. refresh_tokens.device_id
    op.add_column("refresh_tokens", sa.Column("device_id", sa.UUID(), nullable=True))
    op.create_index(op.f("ix_refresh_tokens_device_id"), "refresh_tokens", ["device_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_refresh_tokens_device_id_user_devices"),
        "refresh_tokens",
        "user_devices",
        ["device_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # 4. otp_codes index
    op.create_index(
        "ix_otp_codes_user_purpose_created", "otp_codes", ["user_id", "purpose", "created_at"], unique=False
    )


def downgrade() -> None:
    devices = op.get_bind().execute(sa.text("SELECT count(*) FROM user_devices")).scalar()
    if devices:
        raise RuntimeError(
            f"cannot downgrade 0010: {devices} user_devices row(s) exist; the sign-in records would be lost"
        )
    op.drop_index("ix_otp_codes_user_purpose_created", table_name="otp_codes")
    op.drop_constraint(op.f("fk_refresh_tokens_device_id_user_devices"), "refresh_tokens", type_="foreignkey")
    op.drop_index(op.f("ix_refresh_tokens_device_id"), table_name="refresh_tokens")
    op.drop_column("refresh_tokens", "device_id")
    op.execute("DROP TRIGGER IF EXISTS user_devices_updated_at ON user_devices")
    op.drop_index(op.f("ix_user_devices_user_id"), table_name="user_devices")
    op.drop_table("user_devices")
    op.drop_column("users", "profile_confirmed_at")
    op.drop_column("users", "must_change_password")
    op.drop_column("users", "password_changed_at")
