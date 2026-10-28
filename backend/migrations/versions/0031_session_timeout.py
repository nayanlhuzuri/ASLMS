"""0031 session timeout: one row per sign-in, the refresh token's session

Design `session-timeout` ("Data"; docs/schema/schema.md Group 1). The design planned 0028; 0028 to 0030 were taken by
the time of the build, so this is the next free number (deviation recorded in the design note). Hand-written:
1. the native enum `session_end_reason` (signed_out, idle, limit, replaced, ended);
2. `user_sessions` (derived): CHECKs `ck_user_sessions_times` and `ck_user_sessions_ended`, indexes on `user_id` and
   `device_id`, the partial `ix_user_sessions_open` (last_activity_at) WHERE ended_at IS NULL for the sweep, the class
   comment and the `set_updated_at` trigger;
3. grants as for `user_devices` (0010): ALL to `aslms_owner`, SELECT to `aslms_readonly`, SELECT / INSERT / UPDATE to
   `aslms_app` (never deleted);
4. `refresh_tokens.session_id` (→ user_sessions RESTRICT, NULL) with `ix_refresh_tokens_session_id`.
No data step: tokens issued before this revision have no session and are refused, so everyone signs in once after the
deploy. No reference data changes, so no audit row. The downgrade drops the column, the table and the enum (the
session history is derived; the audit rows stay).

Revision ID: 0031
Revises: 0030
Create Date: 2026-10-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None

# frozen here so the applied migration does not follow later model changes
END_REASONS = ("signed_out", "idle", "limit", "replaced", "ended")


def upgrade() -> None:
    bind = op.get_bind()
    # 1. the enum
    postgresql.ENUM(*END_REASONS, name="session_end_reason").create(bind, checkfirst=False)
    reason_type = postgresql.ENUM(*END_REASONS, name="session_end_reason", create_type=False)

    # 2. user_sessions
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("device_id", sa.UUID(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_reason", reason_type, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "expires_at > started_at AND last_activity_at >= started_at", name=op.f("ck_user_sessions_times")
        ),
        sa.CheckConstraint("(ended_at IS NULL) = (end_reason IS NULL)", name=op.f("ck_user_sessions_ended")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_user_sessions_user_id_users"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["user_devices.id"],
            name=op.f("fk_user_sessions_device_id_user_devices"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_sessions")),
        comment="class=derived",
    )
    op.create_index(op.f("ix_user_sessions_user_id"), "user_sessions", ["user_id"], unique=False)
    op.create_index(op.f("ix_user_sessions_device_id"), "user_sessions", ["device_id"], unique=False)
    op.create_index(
        "ix_user_sessions_open",
        "user_sessions",
        ["last_activity_at"],
        unique=False,
        postgresql_where=sa.text("ended_at IS NULL"),
    )
    op.execute(
        "CREATE TRIGGER user_sessions_updated_at BEFORE UPDATE ON user_sessions "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )

    # 3. grants
    op.execute("GRANT ALL ON user_sessions TO aslms_owner")
    op.execute("GRANT SELECT ON user_sessions TO aslms_readonly")
    op.execute("GRANT SELECT, INSERT, UPDATE ON user_sessions TO aslms_app")

    # 4. refresh_tokens.session_id
    op.add_column("refresh_tokens", sa.Column("session_id", sa.UUID(), nullable=True))
    op.create_index(op.f("ix_refresh_tokens_session_id"), "refresh_tokens", ["session_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_refresh_tokens_session_id_user_sessions"),
        "refresh_tokens",
        "user_sessions",
        ["session_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_refresh_tokens_session_id_user_sessions"), "refresh_tokens", type_="foreignkey"
    )
    op.drop_index(op.f("ix_refresh_tokens_session_id"), table_name="refresh_tokens")
    op.drop_column("refresh_tokens", "session_id")
    op.execute("DROP TRIGGER IF EXISTS user_sessions_updated_at ON user_sessions")
    op.drop_index("ix_user_sessions_open", table_name="user_sessions")
    op.drop_index(op.f("ix_user_sessions_device_id"), table_name="user_sessions")
    op.drop_index(op.f("ix_user_sessions_user_id"), table_name="user_sessions")
    op.drop_table("user_sessions")
    postgresql.ENUM(name="session_end_reason").drop(op.get_bind(), checkfirst=True)
