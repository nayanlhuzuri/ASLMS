"""0008 memberships: one login, several offices; admin tickets and their documents; case-less ticket alerts

Design `user-memberships` (docs/schema/schema.md groups 0, 1, 6, 7; "Data"):
1. Guard: stop, listing the rows, when the data already has more than one active `super_admin` user, or more
   than one active `dept_admin` or `dept_head` user in one department (nothing is fixed silently).
2. `user_memberships` (master) with its partial unique indexes and CHECKs, grants, the `set_updated_at`
   trigger; back-fill one membership per existing user from the login's `office_id`, `role`, `designation`,
   `designation_id` (`department_id` = the office path's second segment when that office is Department-tier).
   An active login's membership is active and primary; a disabled login's is ended (not primary), so the
   one-active indexes only see active logins.
3. `user_permissions.membership_id` (back-filled to that membership, then NOT NULL, FK RESTRICT); the unique
   key moves from (user_id, permission) to (membership_id, permission).
4. `ref_ticket_kind`, enum `ticket_status`, `admin_tickets` (CHECKs, indexes, the freeze trigger,
   `set_updated_at`), `admin_ticket_documents`, `membership_documents` (append-only).
5. `doc_kind` gains `admin` (autocommit block); `ck_documents_user_file` covers it; `ck_documents_admin_file`.
6. `alerts.case_id` DROP NOT NULL; `ck_alerts_case` (only `admin_ticket` alerts are case-less).
7. NOTICE listing every active Department-tier office without an active `dept_head`; nothing is created.
Downgrade stops while any login has more than one membership row or an active non-primary membership, or any
admin ticket, `admin` document or case-less alert exists; otherwise it drops exactly what this revision added
and recreates `doc_kind` without `admin`.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

ROLES = (
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
)
DEPT_KINDS = "('department', 'central', 'advocate_general')"
# the Department-tier ancestor of office `o` (NULL at the State tier)
DEPT_JOIN = (
    "LEFT JOIN offices d ON d.path = split_part(o.path, '/', 1) || '/' || split_part(o.path, '/', 2) "
    f"AND d.kind IN {DEPT_KINDS}"
)
MUTABLE = ("ref_ticket_kind", "user_memberships", "admin_tickets")
APPEND_ONLY = ("admin_ticket_documents", "membership_documents")

USER_FILE_OLD = (
    "kind NOT IN ('upload', 'attachment') OR (ref_no IS NOT NULL AND office_id IS NOT NULL "
    "AND doc_date IS NOT NULL AND virus_scan_status = 'clean' AND doc_group <> 'court_record')"
)
USER_FILE_NEW = (
    "kind NOT IN ('upload', 'attachment', 'admin') OR (ref_no IS NOT NULL AND office_id IS NOT NULL "
    "AND doc_date IS NOT NULL AND virus_scan_status = 'clean' AND doc_group <> 'court_record')"
)
ADMIN_FILE = (
    "kind <> 'admin' OR (case_id IS NULL AND doc_group = 'internal' AND visibility = 'private_to_office')"
)
UPLOAD_CASE = "kind <> 'upload' OR case_id IS NOT NULL"
ALERTS_CASE = "(case_id IS NULL) = (kind = 'admin_ticket')"

GUARD = f"""
DO $$
DECLARE r text;
BEGIN
  SELECT string_agg(email, ', ' ORDER BY email) INTO r FROM users WHERE role = 'super_admin' AND is_active
  HAVING count(*) > 1;
  IF r IS NOT NULL THEN
    RAISE EXCEPTION 'ASLMS 0008: more than one active super admin (%); keep one and disable the others first', r;
  END IF;
  SELECT string_agg(line, '; ') INTO r FROM (
    SELECT d.code || ' ' || u.role || ': ' || string_agg(u.email, ', ' ORDER BY u.email) AS line
    FROM users u JOIN offices o ON o.id = u.office_id {DEPT_JOIN}
    WHERE u.is_active AND u.role IN ('dept_admin', 'dept_head') AND d.id IS NOT NULL
    GROUP BY d.code, u.role HAVING count(*) > 1
  ) x;
  IF r IS NOT NULL THEN
    RAISE EXCEPTION 'ASLMS 0008: more than one active department admin or head in one department (%)', r;
  END IF;
END $$;
"""

BACKFILL = f"""
INSERT INTO user_memberships (
  user_id, office_id, department_id, role, designation, designation_id, is_primary, is_active, deactivated_at,
  valid_from, valid_to, end_reason, created_at, created_by, updated_by
)
SELECT u.id, u.office_id, d.id, u.role, u.designation, u.designation_id, u.is_active, u.is_active,
       CASE WHEN u.is_active THEN NULL ELSE coalesce(u.deactivated_at, now()) END,
       u.valid_from,
       CASE WHEN u.is_active THEN NULL ELSE coalesce(u.deactivated_at, now())::date END,
       CASE WHEN u.is_active THEN NULL ELSE 'login disabled before memberships (migration 0008)' END,
       u.created_at, u.created_by, u.updated_by
FROM users u JOIN offices o ON o.id = u.office_id {DEPT_JOIN}
"""

HEADLESS_NOTICE = f"""
DO $$
DECLARE r text;
BEGIN
  SELECT string_agg(o.code, ', ' ORDER BY o.code) INTO r FROM offices o
  WHERE o.is_active AND o.kind IN {DEPT_KINDS} AND o.parent_id IS NOT NULL
    AND NOT EXISTS (
      SELECT 1 FROM user_memberships m WHERE m.department_id = o.id AND m.role = 'dept_head' AND m.is_active
    );
  IF r IS NOT NULL THEN
    RAISE NOTICE 'ASLMS 0008: departments without a head (set one with the head-change request): %', r;
  END IF;
END $$;
"""

FREEZE_FUNCTION = """
CREATE OR REPLACE FUNCTION aslms_ticket_closed_frozen() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.status <> 'open' THEN
    RAISE EXCEPTION 'admin ticket % is closed and cannot change (ASLMS)', OLD.ref_no
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END $$;
"""

DOWNGRADE_GUARD = """
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM user_memberships GROUP BY user_id HAVING count(*) > 1)
     OR EXISTS (SELECT 1 FROM user_memberships WHERE is_active AND NOT is_primary) THEN
    RAISE EXCEPTION 'ASLMS 0008 downgrade: logins hold several memberships; the old schema cannot hold them';
  END IF;
  IF EXISTS (SELECT 1 FROM admin_tickets) THEN
    RAISE EXCEPTION 'ASLMS 0008 downgrade: admin tickets exist and are legal records';
  END IF;
  IF EXISTS (SELECT 1 FROM documents WHERE kind = 'admin') THEN
    RAISE EXCEPTION 'ASLMS 0008 downgrade: admin documents exist';
  END IF;
  IF EXISTS (SELECT 1 FROM alerts WHERE case_id IS NULL) THEN
    RAISE EXCEPTION 'ASLMS 0008 downgrade: case-less alerts exist';
  END IF;
END $$;
"""


def _role() -> sa.Enum:
    return sa.Enum(*ROLES, name="role", native_enum=False, length=40)


def _actor_columns() -> list[sa.Column]:
    return [
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("actor_name", sa.String(length=200), nullable=True),
        sa.Column("actor_designation", sa.String(length=200), nullable=True),
        sa.Column("actor_office_code", sa.String(length=40), nullable=True),
    ]


def _fk(table: str, col: str, target: str, ondelete: str = "RESTRICT") -> sa.ForeignKeyConstraint:
    ref_table = target.split(".")[0]
    return sa.ForeignKeyConstraint(
        [col], [target], name=op.f(f"fk_{table}_{col}_{ref_table}"), ondelete=ondelete
    )


def _create_memberships() -> None:
    t = "user_memberships"
    op.create_table(
        t,
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("office_id", sa.UUID(), nullable=False),
        sa.Column("department_id", sa.UUID(), nullable=True),
        sa.Column("role", _role(), nullable=False),
        sa.Column("designation", sa.String(length=200), nullable=True),
        sa.Column("designation_id", sa.UUID(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("end_reason", sa.String(length=500), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("valid_from", sa.Date(), server_default=sa.text("current_date"), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.CheckConstraint("NOT is_primary OR is_active", name=op.f("ck_user_memberships_primary_active")),
        sa.CheckConstraint("is_active = (deactivated_at IS NULL)", name=op.f("ck_user_memberships_active")),
        _fk(t, "created_by", "users.id", "SET NULL"),
        _fk(t, "department_id", "offices.id"),
        _fk(t, "designation_id", "designations.id"),
        _fk(t, "office_id", "offices.id"),
        _fk(t, "role", "ref_role.code"),
        _fk(t, "updated_by", "users.id", "SET NULL"),
        _fk(t, "user_id", "users.id"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_memberships")),
        comment="class=master",
    )
    for col in ("department_id", "designation_id", "office_id", "role", "user_id"):
        op.create_index(op.f(f"ix_user_memberships_{col}"), t, [col])
    op.create_index(
        "ix_user_memberships_office_active", t, ["office_id"], postgresql_where=sa.text("is_active")
    )
    op.create_index(
        "ix_user_memberships_one_per_department",
        t,
        ["user_id", "department_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
        postgresql_nulls_not_distinct=True,
    )
    op.create_index(
        "ix_user_memberships_primary",
        t,
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_primary AND is_active"),
    )
    op.create_index(
        "ix_user_memberships_one_super_admin",
        t,
        ["role"],
        unique=True,
        postgresql_where=sa.text("role = 'super_admin' AND is_active"),
    )
    op.create_index(
        "ix_user_memberships_one_dept_admin",
        t,
        ["department_id"],
        unique=True,
        postgresql_where=sa.text("role = 'dept_admin' AND is_active"),
    )
    op.create_index(
        "ix_user_memberships_one_dept_head",
        t,
        ["department_id"],
        unique=True,
        postgresql_where=sa.text("role = 'dept_head' AND is_active"),
    )


def _create_tickets() -> None:
    op.create_table(
        "ref_ticket_kind",
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_ref_ticket_kind")),
        comment="class=reference",
    )
    postgresql.ENUM("open", "approved", "rejected", "withdrawn", name="ticket_status").create(
        op.get_bind(), checkfirst=True
    )
    t = "admin_tickets"
    op.create_table(
        t,
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("ref_no", sa.String(length=40), nullable=False),
        sa.Column(
            "kind", sa.Enum("head_change", name="ticketkind", native_enum=False, length=40), nullable=False
        ),
        sa.Column(
            "status",
            postgresql.ENUM(name="ticket_status", create_type=False),
            server_default="open",
            nullable=False,
        ),
        sa.Column("department_id", sa.UUID(), nullable=True),
        sa.Column("target_user_id", sa.UUID(), nullable=True),
        sa.Column("target_membership_id", sa.UUID(), nullable=True),
        sa.Column("requested_by_user_id", sa.UUID(), nullable=False),
        sa.Column("requested_by_membership_id", sa.UUID(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("request_remark", sa.String(length=2000), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("decision_remark", sa.String(length=2000), nullable=True),
        sa.Column("decided_by_user_id", sa.UUID(), nullable=True),
        sa.Column("decided_by_name", sa.String(length=200), nullable=True),
        sa.Column("decided_by_designation", sa.String(length=200), nullable=True),
        sa.Column("decided_by_office_code", sa.String(length=40), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        *_actor_columns(),
        sa.CheckConstraint("(status = 'open') = (decided_at IS NULL)", name=op.f("ck_admin_tickets_decided")),
        sa.CheckConstraint(
            "kind <> 'head_change' OR department_id IS NOT NULL", name=op.f("ck_admin_tickets_head_change")
        ),
        sa.CheckConstraint(
            "status <> 'rejected' OR decision_remark IS NOT NULL", name=op.f("ck_admin_tickets_reject_remark")
        ),
        _fk(t, "actor_user_id", "users.id", "SET NULL"),
        _fk(t, "decided_by_user_id", "users.id", "SET NULL"),
        _fk(t, "department_id", "offices.id"),
        _fk(t, "kind", "ref_ticket_kind.code"),
        _fk(t, "requested_by_membership_id", "user_memberships.id"),
        _fk(t, "requested_by_user_id", "users.id"),
        _fk(t, "target_membership_id", "user_memberships.id"),
        _fk(t, "target_user_id", "users.id"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_tickets")),
        sa.UniqueConstraint("ref_no", name=op.f("uq_admin_tickets_ref_no")),
        comment="class=transaction",
    )
    for col in (
        "decided_by_user_id",
        "department_id",
        "kind",
        "requested_by_membership_id",
        "requested_by_user_id",
        "target_membership_id",
        "target_user_id",
    ):
        op.create_index(op.f(f"ix_admin_tickets_{col}"), t, [col])
    op.create_index("ix_admin_tickets_department_status", t, ["department_id", "status"])
    op.create_index("ix_admin_tickets_status_created", t, ["status", "created_at"])
    op.create_index(
        "ix_admin_tickets_one_open_head_change",
        t,
        ["department_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'head_change' AND status = 'open'"),
    )
    t = "admin_ticket_documents"
    op.create_table(
        t,
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("ticket_id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        *_actor_columns(),
        _fk(t, "actor_user_id", "users.id", "SET NULL"),
        _fk(t, "document_id", "documents.id"),
        _fk(t, "ticket_id", "admin_tickets.id"),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{t}")),
        sa.UniqueConstraint("ticket_id", "document_id", name=op.f(f"uq_{t}_ticket_id_document_id")),
        comment="class=transaction",
    )
    for col in ("document_id", "ticket_id"):
        op.create_index(op.f(f"ix_{t}_{col}"), t, [col])
    t = "membership_documents"
    op.create_table(
        t,
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("membership_id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("ticket_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        *_actor_columns(),
        _fk(t, "actor_user_id", "users.id", "SET NULL"),
        _fk(t, "document_id", "documents.id"),
        _fk(t, "membership_id", "user_memberships.id"),
        _fk(t, "ticket_id", "admin_tickets.id"),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{t}")),
        sa.UniqueConstraint("membership_id", "document_id", name=op.f(f"uq_{t}_membership_id_document_id")),
        comment="class=transaction",
    )
    for col in ("document_id", "membership_id", "ticket_id"):
        op.create_index(op.f(f"ix_{t}_{col}"), t, [col])
    op.execute(FREEZE_FUNCTION)
    op.execute("ALTER FUNCTION aslms_ticket_closed_frozen() OWNER TO aslms_owner")
    op.execute(
        "CREATE TRIGGER admin_tickets_closed_frozen BEFORE UPDATE ON admin_tickets "
        "FOR EACH ROW EXECUTE FUNCTION aslms_ticket_closed_frozen()"
    )


def upgrade() -> None:
    # 1. guard
    op.execute(GUARD)
    # 2. memberships and the back-fill
    _create_memberships()
    op.execute(BACKFILL)
    # 3. overrides per membership
    op.add_column("user_permissions", sa.Column("membership_id", sa.UUID(), nullable=True))
    op.execute(
        "UPDATE user_permissions p SET membership_id = m.id FROM user_memberships m WHERE m.user_id = p.user_id"
    )
    op.alter_column("user_permissions", "membership_id", existing_type=sa.UUID(), nullable=False)
    op.create_foreign_key(
        op.f("fk_user_permissions_membership_id_user_memberships"),
        "user_permissions",
        "user_memberships",
        ["membership_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(op.f("ix_user_permissions_membership_id"), "user_permissions", ["membership_id"])
    op.drop_constraint(op.f("uq_user_permissions_user_id_permission"), "user_permissions", type_="unique")
    op.create_unique_constraint(
        op.f("uq_user_permissions_membership_id_permission"),
        "user_permissions",
        ["membership_id", "permission"],
    )
    # 4. admin tickets, triggers and grants
    _create_tickets()
    for table in MUTABLE:
        op.execute(
            f"CREATE TRIGGER {table}_updated_at BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
        )
    for table in APPEND_ONLY:
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION aslms_forbid_change()"
        )
    mutable, append_only = ", ".join(MUTABLE), ", ".join(APPEND_ONLY)
    op.execute(f"GRANT ALL ON {mutable}, {append_only} TO aslms_owner")
    op.execute(f"GRANT SELECT ON {mutable}, {append_only} TO aslms_readonly")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {mutable} TO aslms_app")
    op.execute(f"GRANT SELECT, INSERT ON {append_only} TO aslms_app")
    # 5. documents of administrative records
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE doc_kind ADD VALUE IF NOT EXISTS 'admin'")
    op.drop_constraint(op.f("ck_documents_user_file"), "documents", type_="check")
    op.create_check_constraint(op.f("ck_documents_user_file"), "documents", USER_FILE_NEW)
    op.create_check_constraint(op.f("ck_documents_admin_file"), "documents", ADMIN_FILE)
    # 6. case-less ticket alerts
    op.alter_column("alerts", "case_id", existing_type=sa.UUID(), nullable=True)
    op.create_check_constraint(op.f("ck_alerts_case"), "alerts", ALERTS_CASE)
    # 7. departments without a head
    op.execute(HEADLESS_NOTICE)


def downgrade() -> None:
    op.execute(DOWNGRADE_GUARD)
    # 6.
    op.drop_constraint(op.f("ck_alerts_case"), "alerts", type_="check")
    op.alter_column("alerts", "case_id", existing_type=sa.UUID(), nullable=False)
    # 5. doc_kind without `admin`: drop what names the type's labels, swap the type, put them back
    op.drop_constraint(op.f("ck_documents_admin_file"), "documents", type_="check")
    op.drop_constraint(op.f("ck_documents_user_file"), "documents", type_="check")
    op.drop_constraint(op.f("ck_documents_upload_case"), "documents", type_="check")
    op.drop_index("ix_documents_system_sha", table_name="documents")
    op.drop_index("ix_documents_upload_dedupe", table_name="documents")
    op.execute("ALTER TYPE doc_kind RENAME TO doc_kind_0008")
    op.execute("CREATE TYPE doc_kind AS ENUM ('causelist', 'order', 'upload', 'attachment')")
    op.execute("ALTER TABLE documents ALTER COLUMN kind TYPE doc_kind USING kind::text::doc_kind")
    op.execute("DROP TYPE doc_kind_0008")
    op.create_index(
        "ix_documents_system_sha",
        "documents",
        ["kind", "sha256"],
        unique=True,
        postgresql_where=sa.text("kind IN ('causelist', 'order')"),
    )
    op.create_index(
        "ix_documents_upload_dedupe",
        "documents",
        ["case_id", "office_id", "sha256"],
        unique=True,
        postgresql_where=sa.text("kind = 'upload' AND archived_at IS NULL"),
    )
    op.create_check_constraint(op.f("ck_documents_user_file"), "documents", USER_FILE_OLD)
    op.create_check_constraint(op.f("ck_documents_upload_case"), "documents", UPLOAD_CASE)
    # 4.
    op.drop_table("membership_documents")
    op.drop_table("admin_ticket_documents")
    op.drop_table("admin_tickets")
    op.execute("DROP FUNCTION IF EXISTS aslms_ticket_closed_frozen()")
    postgresql.ENUM(name="ticket_status").drop(op.get_bind(), checkfirst=True)
    op.drop_table("ref_ticket_kind")
    # 3.
    op.drop_constraint(
        op.f("uq_user_permissions_membership_id_permission"), "user_permissions", type_="unique"
    )
    op.create_unique_constraint(
        op.f("uq_user_permissions_user_id_permission"), "user_permissions", ["user_id", "permission"]
    )
    op.drop_index(op.f("ix_user_permissions_membership_id"), table_name="user_permissions")
    op.drop_constraint(
        op.f("fk_user_permissions_membership_id_user_memberships"), "user_permissions", type_="foreignkey"
    )
    op.drop_column("user_permissions", "membership_id")
    # 2.
    op.drop_table("user_memberships")
