"""0006 documents: uploads share stored files, per-kind dedupe, the upload CHECKs, the archive reason and the
text-search GIN index

Design `documents-uploads` (docs/schema/schema.md Group 6, "Data"):
- `uq_documents_sha256` is dropped (the same file may be uploaded to two cases or by two offices, and an upload
  whose bytes equal an order PDF must never be attached to the order); a plain index on `sha256` replaces it.
- Partial unique `ix_documents_system_sha` (kind, sha256) WHERE kind IN ('causelist', 'order'): the pipeline's
  dedupe, unchanged in effect. Partial unique `ix_documents_upload_dedupe` (case_id, office_id, sha256) WHERE
  kind = 'upload' AND archived_at IS NULL: the same file twice by one office on one case is refused.
- `archive_reason` text; CHECKs `internal_not_sent` (an internal document is never sent to SourceTrace),
  `user_file` (uploads and attachments carry ref_no, office_id, doc_date, a clean scan and are never court
  records), `upload_case`, `archive_reason`.
- `ix_document_text_search_vector_gin` (schema.md said "GIN"; it was missing) and `ix_documents_case_kind`
  for the Documents tab.
No new table, enum or `ref_*` code; the 0001 grants cover the column and the indexes. The downgrade re-adds
`uq_documents_sha256` only when no duplicate `sha256` exists (else it stops; no data is deleted).

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

# short names; the metadata naming convention makes them ck_documents_<name>
CHECKS = {
    "internal_not_sent": "doc_group <> 'internal' OR sourcetrace_status = 'not_applicable'",
    "user_file": (
        "kind NOT IN ('upload', 'attachment') OR (ref_no IS NOT NULL AND office_id IS NOT NULL "
        "AND doc_date IS NOT NULL AND virus_scan_status = 'clean' AND doc_group <> 'court_record')"
    ),
    "upload_case": "kind <> 'upload' OR case_id IS NOT NULL",
    "archive_reason": "archived_at IS NULL OR archive_reason IS NOT NULL",
}


def upgrade() -> None:
    op.add_column("documents", sa.Column("archive_reason", sa.Text(), nullable=True))
    op.drop_constraint("uq_documents_sha256", "documents", type_="unique")
    op.create_index("ix_documents_sha256", "documents", ["sha256"], unique=False)
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
    op.create_index(
        "ix_documents_case_kind",
        "documents",
        ["case_id", "kind"],
        unique=False,
        postgresql_where=sa.text("archived_at IS NULL"),
    )
    for name, expr in CHECKS.items():
        op.create_check_constraint(name, "documents", expr)
    op.create_index(
        "ix_document_text_search_vector_gin",
        "document_text",
        ["search_vector"],
        unique=False,
        postgresql_using="gin",
    )


def downgrade() -> None:
    dupes = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT count(*) FROM (SELECT sha256 FROM documents GROUP BY sha256 HAVING count(*) > 1) d"
            )
        )
        .scalar()
    )
    if dupes:
        raise RuntimeError(
            f"cannot downgrade 0006: {dupes} sha256 value(s) back more than one documents row; "
            "uq_documents_sha256 cannot be restored without deleting legal records"
        )
    op.drop_index("ix_document_text_search_vector_gin", table_name="document_text", postgresql_using="gin")
    for name in CHECKS:
        op.drop_constraint(name, "documents", type_="check")
    op.drop_index("ix_documents_case_kind", table_name="documents")
    op.drop_index("ix_documents_upload_dedupe", table_name="documents")
    op.drop_index("ix_documents_system_sha", table_name="documents")
    op.drop_index("ix_documents_sha256", table_name="documents")
    op.create_unique_constraint("uq_documents_sha256", "documents", ["sha256"])
    op.drop_column("documents", "archive_reason")
