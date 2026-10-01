"""0003 access control: ref_permission, role_permissions (the type matrix), user_permissions (overrides)

The user type (`ref_role`, now with `super_admin`) gets an explicit set of functions per type and per user
(docs/schema/schema.md groups 0 and 1; decisions log 1 Oct 2026). New codes in `ref_role`, `ref_event_type`
and `ref_permission` are seed rows.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

ROLES = [
    "super_admin",
    "state_oversight",
    "dept_head",
    "dept_admin",
    "dept_officer",
    "directorate_user",
    "referral_reviewer",
    "standing_counsel",
    "central_operator",
    "auditor",
]
PERMISSIONS = [
    "users.view", "users.create", "users.edit", "users.set_type", "users.enable_disable", "users.grant",
    "users.reset_password", "access.manage_types", "offices.manage", "admin.counsel_codes", "admin.keywords",
    "admin.watchlist", "admin.masters_sync", "admin.napix_refetch", "admin.config", "cases.view_scope",
    "cases.view_all", "cases.search_court", "cases.claim", "cases.dismiss", "cases.suggest_elsewhere",
    "cases.transfer_request", "cases.transfer_decide", "cases.allot", "cases.release", "custody.move",
    "requests.send", "requests.answer", "stages.set", "notes.add", "notes.view_counsel_shared",
    "notes.view_private_office", "documents.upload", "documents.view", "documents.download",
    "alerts.acknowledge", "next_dates.review", "reports.department", "reports.state", "dashboard.state",
    "assistant.use", "audit.view",
]  # fmt: skip
NEW_TABLES = ["ref_permission", "role_permissions", "user_permissions"]


def _role_code() -> sa.Enum:
    return sa.Enum(*ROLES, name="role", native_enum=False, length=40)


def _permission_code() -> sa.Enum:
    return sa.Enum(*PERMISSIONS, name="permission", native_enum=False, length=40)


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM("grant", "deny", name="permission_effect").create(bind, checkfirst=True)

    op.create_table(
        "ref_permission",
        sa.Column("module", sa.String(length=40), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_ref_permission")),
        comment="class=reference",
    )
    op.create_index(op.f("ix_ref_permission_module"), "ref_permission", ["module"], unique=False)

    op.create_table(
        "role_permissions",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("role", _role_code(), nullable=False),
        sa.Column("permission", _permission_code(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_role_permissions_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["permission"],
            ["ref_permission.code"],
            name=op.f("fk_role_permissions_permission_ref_permission"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["role"], ["ref_role.code"], name=op.f("fk_role_permissions_role_ref_role"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_role_permissions_updated_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_role_permissions")),
        sa.UniqueConstraint("role", "permission", name=op.f("uq_role_permissions_role_permission")),
        comment="class=master",
    )
    op.create_index(op.f("ix_role_permissions_permission"), "role_permissions", ["permission"], unique=False)
    op.create_index(op.f("ix_role_permissions_role"), "role_permissions", ["role"], unique=False)

    op.create_table(
        "user_permissions",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("permission", _permission_code(), nullable=False),
        sa.Column(
            "effect",
            postgresql.ENUM("grant", "deny", name="permission_effect", create_type=False),
            server_default="grant",
            nullable=False,
        ),
        sa.Column("granted_by_user_id", sa.UUID(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("valid_from", sa.Date(), server_default=sa.text("current_date"), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actor_name", sa.String(length=200), nullable=True),
        sa.Column("actor_designation", sa.String(length=200), nullable=True),
        sa.Column("actor_office_code", sa.String(length=40), nullable=True),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_user_permissions_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by_user_id"],
            ["users.id"],
            name=op.f("fk_user_permissions_granted_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["permission"],
            ["ref_permission.code"],
            name=op.f("fk_user_permissions_permission_ref_permission"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_user_permissions_user_id_users"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_permissions")),
        sa.UniqueConstraint("user_id", "permission", name=op.f("uq_user_permissions_user_id_permission")),
        comment="class=master",
    )
    op.create_index(
        op.f("ix_user_permissions_granted_by_user_id"),
        "user_permissions",
        ["granted_by_user_id"],
        unique=False,
    )
    op.create_index(op.f("ix_user_permissions_permission"), "user_permissions", ["permission"], unique=False)
    op.create_index(op.f("ix_user_permissions_user_id"), "user_permissions", ["user_id"], unique=False)

    for table in NEW_TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_updated_at BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
        )
    tables = ", ".join(NEW_TABLES)
    op.execute(f"GRANT ALL ON {tables} TO aslms_owner")
    op.execute(f"GRANT SELECT ON {tables} TO aslms_readonly")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {tables} TO aslms_app")


def downgrade() -> None:
    op.drop_index(op.f("ix_user_permissions_user_id"), table_name="user_permissions")
    op.drop_index(op.f("ix_user_permissions_permission"), table_name="user_permissions")
    op.drop_index(op.f("ix_user_permissions_granted_by_user_id"), table_name="user_permissions")
    op.drop_table("user_permissions")
    op.drop_index(op.f("ix_role_permissions_role"), table_name="role_permissions")
    op.drop_index(op.f("ix_role_permissions_permission"), table_name="role_permissions")
    op.drop_table("role_permissions")
    op.drop_index(op.f("ix_ref_permission_module"), table_name="ref_permission")
    op.drop_table("ref_permission")
    postgresql.ENUM(name="permission_effect").drop(op.get_bind(), checkfirst=True)
