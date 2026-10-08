"""0011 sourcetrace: the ingestion queue columns on `documents` and the append-only attempt record

Design `sourcetrace-connector` ("Data"; docs/schema/schema.md Group 6 and "Phase 2 and 3 tables"):
1. Guard: stop if any `sourcetrace_ingestions` row exists (none was ever written; the new NOT NULL columns
   assume an empty table).
2. Back-fill: archived `pending` / `failed` documents become `not_applicable` (decision 9); then stop with the
   counts if any row would break the new CHECKs.
3. `documents.sourcetrace_attempts`, `sourcetrace_next_at`, `sourcetrace_ingested_at`; CHECKs
   `ck_documents_sourcetrace_kind`, `ck_documents_private_not_sent`, `ck_documents_sourcetrace_ingested`; the
   partial index `ix_documents_sourcetrace_due`.
4. `sourcetrace_ingestions.connector`, `error_family`, `duration_ms`, `response`; `metadata_sent` NOT NULL; CHECK
   `ck_sourcetrace_ingestions_outcome`; `ix_sourcetrace_ingestions_document_created` replaces
   `ix_sourcetrace_ingestions_document_id`; the append-only trigger; `aslms_app` loses UPDATE and DELETE.
No enum, `ref_*` code set or permission row is added here (`admin.sourcetrace` comes from `aslms seed`). The
downgrade stops while an attempt row exists or a document carries attempts or an ingestion time; otherwise it
drops exactly what steps 3–4 added and restores the grant and the index. Back-filled statuses stay
`not_applicable` (consistent with the 0006 rules).

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

CHECK_BREAKERS = {
    "sourcetrace_kind": (
        "SELECT count(*) FROM documents WHERE sourcetrace_status <> 'not_applicable' "
        "AND kind NOT IN ('order', 'upload')"
    ),
    "private_not_sent": (
        "SELECT count(*) FROM documents WHERE visibility = 'private_to_office' "
        "AND sourcetrace_status <> 'not_applicable'"
    ),
    # sourcetrace_ingested_at is new, so any `ingested` row would break the CHECK (none was ever written)
    "sourcetrace_ingested": "SELECT count(*) FROM documents WHERE sourcetrace_status = 'ingested'",
}


def upgrade() -> None:
    bind = op.get_bind()
    # 1. guard
    rows = bind.execute(sa.text("SELECT count(*) FROM sourcetrace_ingestions")).scalar()
    if rows:
        raise RuntimeError(
            f"cannot upgrade to 0011: {rows} sourcetrace_ingestions row(s) exist; expected none"
        )

    # 2. back-fill and verify
    op.execute(
        "UPDATE documents SET sourcetrace_status = 'not_applicable' "
        "WHERE archived_at IS NOT NULL AND sourcetrace_status IN ('pending', 'failed')"
    )
    counts = {name: bind.execute(sa.text(sql)).scalar() for name, sql in CHECK_BREAKERS.items()}
    broken = {k: v for k, v in counts.items() if v}
    if broken:
        raise RuntimeError(f"cannot upgrade to 0011: documents would break the new CHECKs: {broken}")

    # 3. documents
    op.add_column(
        "documents",
        sa.Column("sourcetrace_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column("documents", sa.Column("sourcetrace_next_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "documents", sa.Column("sourcetrace_ingested_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(
        op.f("ck_documents_sourcetrace_kind"),
        "documents",
        "sourcetrace_status = 'not_applicable' OR kind IN ('order', 'upload')",
    )
    op.create_check_constraint(
        op.f("ck_documents_private_not_sent"),
        "documents",
        "visibility <> 'private_to_office' OR sourcetrace_status = 'not_applicable'",
    )
    op.create_check_constraint(
        op.f("ck_documents_sourcetrace_ingested"),
        "documents",
        "sourcetrace_status <> 'ingested' OR (sourcetrace_ref IS NOT NULL AND sourcetrace_ingested_at IS NOT NULL)",
    )
    op.create_index(
        "ix_documents_sourcetrace_due",
        "documents",
        ["sourcetrace_next_at"],
        unique=False,
        postgresql_where=sa.text("sourcetrace_status = 'pending'"),
    )

    # 4. sourcetrace_ingestions
    op.add_column("sourcetrace_ingestions", sa.Column("connector", sa.String(length=40), nullable=False))
    op.add_column("sourcetrace_ingestions", sa.Column("error_family", sa.String(length=40), nullable=True))
    op.add_column(
        "sourcetrace_ingestions",
        sa.Column("duration_ms", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "sourcetrace_ingestions",
        sa.Column("response", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.alter_column(
        "sourcetrace_ingestions",
        "metadata_sent",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        nullable=False,
    )
    op.create_check_constraint(
        op.f("ck_sourcetrace_ingestions_outcome"),
        "sourcetrace_ingestions",
        "(ok AND reference IS NOT NULL AND error_family IS NULL) OR "
        "(NOT ok AND error IS NOT NULL AND error_family IS NOT NULL)",
    )
    op.drop_index(op.f("ix_sourcetrace_ingestions_document_id"), table_name="sourcetrace_ingestions")
    op.create_index(
        "ix_sourcetrace_ingestions_document_created",
        "sourcetrace_ingestions",
        ["document_id", "created_at"],
        unique=False,
    )
    op.execute(
        "CREATE TRIGGER sourcetrace_ingestions_append_only BEFORE UPDATE OR DELETE ON sourcetrace_ingestions "
        "FOR EACH ROW EXECUTE FUNCTION aslms_forbid_change()"
    )
    op.execute("REVOKE UPDATE, DELETE ON sourcetrace_ingestions FROM aslms_app")


def downgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT count(*) FROM sourcetrace_ingestions")).scalar()
    touched = bind.execute(
        sa.text(
            "SELECT count(*) FROM documents WHERE sourcetrace_attempts > 0 OR sourcetrace_ingested_at IS NOT NULL"
        )
    ).scalar()
    if rows or touched:
        raise RuntimeError(
            f"cannot downgrade 0011: {rows} sourcetrace_ingestions row(s) and {touched} document(s) with "
            "SourceTrace attempts or an ingestion time exist; the ingestion record would be lost"
        )
    op.execute("GRANT UPDATE, DELETE ON sourcetrace_ingestions TO aslms_app")
    op.execute("DROP TRIGGER IF EXISTS sourcetrace_ingestions_append_only ON sourcetrace_ingestions")
    op.drop_index("ix_sourcetrace_ingestions_document_created", table_name="sourcetrace_ingestions")
    op.create_index(
        op.f("ix_sourcetrace_ingestions_document_id"), "sourcetrace_ingestions", ["document_id"], unique=False
    )
    op.drop_constraint(op.f("ck_sourcetrace_ingestions_outcome"), "sourcetrace_ingestions", type_="check")
    op.alter_column(
        "sourcetrace_ingestions",
        "metadata_sent",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        nullable=True,
    )
    op.drop_column("sourcetrace_ingestions", "response")
    op.drop_column("sourcetrace_ingestions", "duration_ms")
    op.drop_column("sourcetrace_ingestions", "error_family")
    op.drop_column("sourcetrace_ingestions", "connector")
    op.drop_index(
        "ix_documents_sourcetrace_due",
        table_name="documents",
        postgresql_where=sa.text("sourcetrace_status = 'pending'"),
    )
    op.drop_constraint(op.f("ck_documents_sourcetrace_ingested"), "documents", type_="check")
    op.drop_constraint(op.f("ck_documents_private_not_sent"), "documents", type_="check")
    op.drop_constraint(op.f("ck_documents_sourcetrace_kind"), "documents", type_="check")
    op.drop_column("documents", "sourcetrace_ingested_at")
    op.drop_column("documents", "sourcetrace_next_at")
    op.drop_column("documents", "sourcetrace_attempts")
