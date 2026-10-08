"""0012 report indexes: two indexes for the period reports, no table or column

Design `reports-dashboards` ("Data"; docs/schema/schema.md Group 3, "Reporting indexes"):
- `ix_cases_disposal_date` on `cases (disposal_date) WHERE disposal_date IS NOT NULL` — the disposals of a period
  (`hearings-disposals`).
- `ix_case_hearings_business_date` on `case_hearings (business_date)` — the proceedings of a period (the unique
  key (case_id, business_date, purpose) leads with `case_id` and does not serve a date range).
No enum, grant, trigger, `ref_*` code or permission is added; indexes need no grant. The downgrade drops the two
indexes.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_case_hearings_business_date", "case_hearings", ["business_date"], unique=False)
    op.create_index(
        "ix_cases_disposal_date",
        "cases",
        ["disposal_date"],
        unique=False,
        postgresql_where=sa.text("disposal_date IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_cases_disposal_date", table_name="cases")
    op.drop_index("ix_case_hearings_business_date", table_name="case_hearings")
