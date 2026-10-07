"""0009 workflow: sending the file and recall replace requests; the holder is a membership; draft notes

Design `custody-workflow` (docs/schema/schema.md "Phase 2 and 3 tables", "Data"):
1. Guard: stop unless `requests` and `request_messages` are empty and no `custody` / `custody_history` row has a
   `request_id` (no legal record is dropped).
2. `pending_action` gains `parawise_comments`, `report`, `documents`, `opinion`, `instructions`,
   `clarification`, `other` (autocommit block; PostgreSQL cannot drop enum values, so the downgrade leaves them).
3. Drop the `request_id` FKs, indexes and columns of `custody` and `custody_history`, then `request_messages`,
   `requests`, `ref_request_kind` and the `request_status` enum.
4. `custody.holder_membership_id`, `custody_history.holder_membership_id`, `holder_designation`, `remark`,
   `case_notes.drafted_at`; back-fill the holder membership of legs naming a person (the person's membership at
   the holder office, else one whose subtree relates to it, the active one first) and the remark of exit-step
   legs written before this revision (from their `custody_moved` event); the append-only trigger of
   `custody_history` is switched off for the back-fill only.
5. CHECKs `ck_custody_history_reason`, `ck_custody_history_remark`, `ck_case_notes_not_self`; indexes
   `ix_custody_due` (partial), `ix_case_notes_supersedes` (partial unique), `ix_case_stages_case_created`.
6. `case_note_drafts` (`set_updated_at`) and `case_note_draft_documents`, class `transaction`, grants
   SELECT/INSERT/UPDATE/DELETE for `aslms_app` (the owner's deviation from DB_STANDARD §6 / §9: drafts are not
   legal records).
7. `case_note_attachments` becomes append-only: trigger `aslms_forbid_change`, no UPDATE for `aslms_app`.
The `ref_*` codes (note kinds, the `workflow` alert kind, `custody.recall`, `custody.track`, the retired codes)
are seed rows. Downgrade stops while drafts exist, a note came from a draft, or a leg is `sent` or `recalled`;
otherwise it recreates the dropped tables and columns empty (the 0001 shapes) and leaves the enum values.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

NEW_PENDING_ACTIONS = (
    "parawise_comments",
    "report",
    "documents",
    "opinion",
    "instructions",
    "clarification",
    "other",
)
REASONS = ("claimed", "allotted", "taken_over", "transferred", "sent", "recalled", "reassigned_on_exit")
REMARK_REASONS = ("sent", "recalled", "reassigned_on_exit")
DRAFT_TABLES = ("case_note_drafts", "case_note_draft_documents")
REQUEST_INDEXED = (
    "answered_by_user_id",
    "case_id",
    "from_office_id",
    "kind",
    "status",
    "to_office_id",
    "to_user_id",
)
DUE_WHERE = sa.text("due_date IS NOT NULL")
SUPERSEDES_WHERE = sa.text("supersedes_id IS NOT NULL")
NOTE_KINDS = (
    "general",
    "decision",
    "instruction",
    "hearing",
    "counsel_advice",
    "compliance",
    "file_noting",
    "correction",
    "opinion",
    "hand_over",
)
REQUEST_KINDS = (
    "report",
    "parawise_comments",
    "documents",
    "opinion",
    "instructions",
    "compliance",
    "clarification",
    "other",
)


def _in(values: tuple[str, ...]) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


GUARD = """
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM requests) OR EXISTS (SELECT 1 FROM request_messages) THEN
    RAISE EXCEPTION 'ASLMS 0009: requests or request messages exist; they are legal records and are not dropped';
  END IF;
  IF EXISTS (SELECT 1 FROM custody WHERE request_id IS NOT NULL)
     OR EXISTS (SELECT 1 FROM custody_history WHERE request_id IS NOT NULL) THEN
    RAISE EXCEPTION 'ASLMS 0009: custody rows point at requests; nothing is dropped';
  END IF;
END $$;
"""

# the holder membership of a leg naming a person: their membership at the holder office, else one whose
# office subtree contains the holder office or lies inside it; the active one first, then the newest
BACKFILL_LEG_MEMBERSHIP = """
UPDATE custody_history h
SET holder_membership_id = pick.id, holder_designation = pick.designation
FROM (
  SELECT DISTINCT ON (h2.id) h2.id AS leg_id, m.id, m.designation
  FROM custody_history h2
  JOIN offices ho ON ho.id = h2.holder_office_id
  JOIN user_memberships m ON m.user_id = h2.holder_user_id
  JOIN offices mo ON mo.id = m.office_id
  WHERE h2.holder_user_id IS NOT NULL
    AND (mo.id = ho.id OR ho.path LIKE mo.path || '/%' OR mo.path LIKE ho.path || '/%')
  ORDER BY h2.id, (mo.id = ho.id) DESC, m.is_active DESC, m.created_at DESC
) pick
WHERE h.id = pick.leg_id
"""
BACKFILL_EXIT_REMARK = """
UPDATE custody_history h
SET remark = left(e.payload ->> 'remark', 2000)
FROM events e
WHERE h.reason = 'reassigned_on_exit' AND h.remark IS NULL
  AND e.dedupe_key = 'custody_moved:' || h.case_id::text || ':' || h.seq_no::text
  AND e.payload ->> 'remark' IS NOT NULL
"""
# an exit-step leg whose event carries no remark (none is known to exist): say so rather than invent one
BACKFILL_EXIT_REMARK_MISSING = """
UPDATE custody_history
SET remark = 'Reassigned on an officer''s exit (remark not recorded before migration 0009)'
WHERE reason = 'reassigned_on_exit' AND remark IS NULL
"""
BACKFILL_CUSTODY_MEMBERSHIP = """
UPDATE custody c SET holder_membership_id = h.holder_membership_id
FROM custody_history h WHERE h.id = c.current_leg_id AND c.holder_user_id IS NOT NULL
"""

DOWNGRADE_GUARD = """
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM case_note_drafts) THEN
    RAISE EXCEPTION 'ASLMS 0009 downgrade: draft notes exist; send or recall the files first';
  END IF;
  IF EXISTS (SELECT 1 FROM case_notes WHERE drafted_at IS NOT NULL) THEN
    RAISE EXCEPTION 'ASLMS 0009 downgrade: notes made permanent from drafts exist (drafted_at would be lost)';
  END IF;
  IF EXISTS (SELECT 1 FROM custody_history WHERE reason IN ('sent', 'recalled')) THEN
    RAISE EXCEPTION 'ASLMS 0009 downgrade: files were sent or recalled; the old schema cannot hold those legs';
  END IF;
END $$;
"""


def _drop_requests() -> None:
    for table in ("custody", "custody_history"):
        op.drop_index(op.f(f"ix_{table}_request_id"), table_name=table)
        op.drop_constraint(op.f(f"fk_{table}_request_id_requests"), table, type_="foreignkey")
        op.drop_column(table, "request_id")
    op.drop_index(op.f("ix_request_messages_request_id"), table_name="request_messages")
    op.drop_table("request_messages")
    for col in REQUEST_INDEXED:
        op.drop_index(op.f(f"ix_requests_{col}"), table_name="requests")
    op.drop_table("requests")
    op.drop_table("ref_request_kind")
    postgresql.ENUM(name="request_status").drop(op.get_bind(), checkfirst=True)


def _create_drafts() -> None:
    op.create_table(
        "case_note_drafts",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("membership_id", sa.UUID(), nullable=False),
        sa.Column("author_user_id", sa.UUID(), nullable=False),
        sa.Column("custody_leg_id", sa.UUID(), nullable=False),
        sa.Column(
            "kind", sa.Enum(*NOTE_KINDS, name="notekind", native_enum=False, length=40), nullable=False
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("visibility", postgresql.ENUM(name="doc_visibility", create_type=False), nullable=False),
        sa.Column("supersedes_id", sa.UUID(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_name", sa.String(length=200), nullable=True),
        sa.Column("actor_designation", sa.String(length=200), nullable=True),
        sa.Column("actor_office_code", sa.String(length=40), nullable=True),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_case_note_drafts_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["author_user_id"],
            ["users.id"],
            name=op.f("fk_case_note_drafts_author_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_case_note_drafts_case_id_cases"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["custody_leg_id"],
            ["custody_history.id"],
            name=op.f("fk_case_note_drafts_custody_leg_id_custody_history"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["kind"],
            ["ref_note_kind.code"],
            name=op.f("fk_case_note_drafts_kind_ref_note_kind"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["membership_id"],
            ["user_memberships.id"],
            name=op.f("fk_case_note_drafts_membership_id_user_memberships"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            ["case_notes.id"],
            name=op.f("fk_case_note_drafts_supersedes_id_case_notes"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_case_note_drafts")),
        comment="class=transaction",
    )
    for col in ("author_user_id", "case_id", "custody_leg_id", "kind", "membership_id", "supersedes_id"):
        op.create_index(op.f(f"ix_case_note_drafts_{col}"), "case_note_drafts", [col], unique=False)
    op.create_index(
        "ix_case_note_drafts_case_membership", "case_note_drafts", ["case_id", "membership_id"], unique=False
    )
    op.create_table(
        "case_note_draft_documents",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("draft_id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_case_note_draft_documents_document_id_documents"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["draft_id"],
            ["case_note_drafts.id"],
            name=op.f("fk_case_note_draft_documents_draft_id_case_note_drafts"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_case_note_draft_documents")),
        sa.UniqueConstraint(
            "draft_id", "document_id", name=op.f("uq_case_note_draft_documents_draft_id_document_id")
        ),
        comment="class=transaction",
    )
    for col in ("document_id", "draft_id"):
        op.create_index(
            op.f(f"ix_case_note_draft_documents_{col}"), "case_note_draft_documents", [col], unique=False
        )
    op.execute(
        "CREATE TRIGGER case_note_drafts_updated_at BEFORE UPDATE ON case_note_drafts "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )
    tables = ", ".join(DRAFT_TABLES)
    op.execute(f"GRANT ALL ON {tables} TO aslms_owner")
    op.execute(f"GRANT SELECT ON {tables} TO aslms_readonly")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {tables} TO aslms_app")


def upgrade() -> None:
    # 1. guard
    op.execute(GUARD)
    # 2. pending actions (decision 10)
    with op.get_context().autocommit_block():
        for value in NEW_PENDING_ACTIONS:
            op.execute(f"ALTER TYPE pending_action ADD VALUE IF NOT EXISTS '{value}'")
    # 3. the request tables (decision 27)
    _drop_requests()
    # 4. the holder membership, the remark, drafted_at, and their back-fill
    for table in ("custody", "custody_history"):
        op.add_column(table, sa.Column("holder_membership_id", sa.UUID(), nullable=True))
        op.create_index(
            op.f(f"ix_{table}_holder_membership_id"), table, ["holder_membership_id"], unique=False
        )
        op.create_foreign_key(
            op.f(f"fk_{table}_holder_membership_id_user_memberships"),
            table,
            "user_memberships",
            ["holder_membership_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    op.add_column("custody_history", sa.Column("holder_designation", sa.String(length=200), nullable=True))
    op.add_column("custody_history", sa.Column("remark", sa.String(length=2000), nullable=True))
    op.add_column("case_notes", sa.Column("drafted_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("ALTER TABLE custody_history DISABLE TRIGGER custody_history_append_only")
    op.execute(BACKFILL_LEG_MEMBERSHIP)
    op.execute(BACKFILL_EXIT_REMARK)
    op.execute(BACKFILL_EXIT_REMARK_MISSING)
    op.execute("ALTER TABLE custody_history ENABLE TRIGGER custody_history_append_only")
    op.execute(BACKFILL_CUSTODY_MEMBERSHIP)
    # 5. CHECKs and indexes
    op.create_check_constraint(
        op.f("ck_custody_history_reason"), "custody_history", f"reason IN {_in(REASONS)}"
    )
    op.create_check_constraint(
        op.f("ck_custody_history_remark"),
        "custody_history",
        f"reason NOT IN {_in(REMARK_REASONS)} OR remark IS NOT NULL",
    )
    op.create_check_constraint(op.f("ck_case_notes_not_self"), "case_notes", "supersedes_id <> id")
    op.create_index("ix_custody_due", "custody", ["due_date"], unique=False, postgresql_where=DUE_WHERE)
    op.create_index(
        "ix_case_notes_supersedes",
        "case_notes",
        ["supersedes_id"],
        unique=True,
        postgresql_where=SUPERSEDES_WHERE,
    )
    op.create_index(
        "ix_case_stages_case_created",
        "case_stages",
        ["case_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    # 6. drafts
    _create_drafts()
    # 7. attachments are append-only
    op.execute(
        "CREATE TRIGGER case_note_attachments_append_only BEFORE UPDATE OR DELETE ON case_note_attachments "
        "FOR EACH ROW EXECUTE FUNCTION aslms_forbid_change()"
    )
    op.execute("REVOKE UPDATE ON case_note_attachments FROM aslms_app")


def _recreate_requests() -> None:
    postgresql.ENUM("open", "answered", "withdrawn", name="request_status").create(
        op.get_bind(), checkfirst=True
    )
    op.create_table(
        "ref_request_kind",
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_ref_request_kind")),
        comment="class=reference",
    )
    op.create_table(
        "requests",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column(
            "kind", sa.Enum(*REQUEST_KINDS, name="requestkind", native_enum=False, length=40), nullable=False
        ),
        sa.Column("from_office_id", sa.UUID(), nullable=False),
        sa.Column("to_office_id", sa.UUID(), nullable=False),
        sa.Column("to_user_id", sa.UUID(), nullable=True),
        sa.Column("subject", sa.String(length=300), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(name="request_status", create_type=False),
            server_default="open",
            nullable=False,
        ),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("answered_by_user_id", sa.UUID(), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("ref_no", sa.String(length=40), nullable=False),
        sa.Column("actor_name", sa.String(length=200), nullable=True),
        sa.Column("actor_designation", sa.String(length=200), nullable=True),
        sa.Column("actor_office_code", sa.String(length=40), nullable=True),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], name=op.f("fk_requests_actor_user_id_users"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["answered_by_user_id"],
            ["users.id"],
            name=op.f("fk_requests_answered_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_requests_case_id_cases"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["from_office_id"],
            ["offices.id"],
            name=op.f("fk_requests_from_office_id_offices"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["kind"],
            ["ref_request_kind.code"],
            name=op.f("fk_requests_kind_ref_request_kind"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["to_office_id"],
            ["offices.id"],
            name=op.f("fk_requests_to_office_id_offices"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["to_user_id"], ["users.id"], name=op.f("fk_requests_to_user_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_requests")),
        sa.UniqueConstraint("ref_no", name=op.f("uq_requests_ref_no")),
        comment="class=transaction",
    )
    for col in REQUEST_INDEXED:
        op.create_index(op.f(f"ix_requests_{col}"), "requests", [col], unique=False)
    op.create_table(
        "request_messages",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("request_id", sa.UUID(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_answer", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_name", sa.String(length=200), nullable=True),
        sa.Column("actor_designation", sa.String(length=200), nullable=True),
        sa.Column("actor_office_code", sa.String(length=40), nullable=True),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_request_messages_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["requests.id"],
            name=op.f("fk_request_messages_request_id_requests"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_request_messages")),
        comment="class=transaction",
    )
    op.create_index(op.f("ix_request_messages_request_id"), "request_messages", ["request_id"], unique=False)
    for table in ("ref_request_kind", "requests"):
        op.execute(
            f"CREATE TRIGGER {table}_updated_at BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
        )
    tables = "ref_request_kind, requests, request_messages"
    op.execute(f"GRANT ALL ON {tables} TO aslms_owner")
    op.execute(f"GRANT SELECT ON {tables} TO aslms_readonly")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {tables} TO aslms_app")
    for table in ("custody", "custody_history"):
        op.add_column(table, sa.Column("request_id", sa.UUID(), nullable=True))
        op.create_foreign_key(
            op.f(f"fk_{table}_request_id_requests"),
            table,
            "requests",
            ["request_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        op.create_index(op.f(f"ix_{table}_request_id"), table, ["request_id"], unique=False)


def downgrade() -> None:
    op.execute(DOWNGRADE_GUARD)
    # 7.
    op.execute("DROP TRIGGER IF EXISTS case_note_attachments_append_only ON case_note_attachments")
    op.execute("GRANT UPDATE ON case_note_attachments TO aslms_app")
    # 6.
    op.drop_table("case_note_draft_documents")
    op.drop_table("case_note_drafts")
    # 5.
    op.drop_index("ix_case_stages_case_created", table_name="case_stages")
    op.drop_index("ix_case_notes_supersedes", table_name="case_notes", postgresql_where=SUPERSEDES_WHERE)
    op.drop_index("ix_custody_due", table_name="custody", postgresql_where=DUE_WHERE)
    op.drop_constraint(op.f("ck_case_notes_not_self"), "case_notes", type_="check")
    op.drop_constraint(op.f("ck_custody_history_remark"), "custody_history", type_="check")
    op.drop_constraint(op.f("ck_custody_history_reason"), "custody_history", type_="check")
    # 4.
    op.drop_column("case_notes", "drafted_at")
    op.drop_column("custody_history", "remark")
    op.drop_column("custody_history", "holder_designation")
    for table in ("custody_history", "custody"):
        op.drop_constraint(
            op.f(f"fk_{table}_holder_membership_id_user_memberships"), table, type_="foreignkey"
        )
        op.drop_index(op.f(f"ix_{table}_holder_membership_id"), table_name=table)
        op.drop_column(table, "holder_membership_id")
    # 3.
    _recreate_requests()
    # 2. the added pending_action values stay (PostgreSQL cannot drop enum values; harmless)
