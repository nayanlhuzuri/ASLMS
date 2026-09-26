"""ownership unit

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-26 21:18:55.074690
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("case_ownership", sa.Column("unit_office_id", sa.UUID(), nullable=True))
    op.create_index(
        op.f("ix_case_ownership_unit_office_id"), "case_ownership", ["unit_office_id"], unique=False
    )
    op.create_foreign_key(
        op.f("fk_case_ownership_unit_office_id_offices"),
        "case_ownership",
        "offices",
        ["unit_office_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_case_ownership_unit_office_id_offices"), "case_ownership", type_="foreignkey")
    op.drop_index(op.f("ix_case_ownership_unit_office_id"), table_name="case_ownership")
    op.drop_column("case_ownership", "unit_office_id")
