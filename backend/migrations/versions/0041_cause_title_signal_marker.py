"""0041 cause title signal marker: each phrase's department and the durable rescore mark on the Insights readings

Design `cause-title-signal-review-advisories`, decisions 6 and 8 ("Data"); docs/schema/schema.md, the
`insight_case_facts` paragraph. Hand-written: two columns, one CHECK and one partial index on a derived table. No
data step (the positions are filled by the first `insights-refresh` after the deploy, because the attribution rules
are code: `ATTRIBUTION_VERSION` moves the attribution fingerprint), no audit row (a schema change to a derived table, as
0039), no type, trigger or grant change (`aslms_app` already has SELECT / INSERT / UPDATE on `insight_case_facts`;
the `set_updated_at` trigger of 0039 stays).

Upgrade:
1. `title_phrase_department_pos smallint[] NOT NULL DEFAULT '{}'` (metadata only in PostgreSQL 16: no rewrite).
2. `named_changed_at timestamptz NULL`.
3. CHECK `ck_insight_case_facts_phrase_pos`: empty, or one element per phrase, none NULL, each between 0 and the number
   of departments named.
4. Partial index `ix_insight_case_facts_named_changed_at` (named_changed_at) WHERE named_changed_at IS NOT NULL.

Downgrade: the index, the CHECK and both columns are dropped.

Revision ID: 0041
Revises: 0040
Create Date: 2026-11-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None

TABLE = "insight_case_facts"
PHRASE_POS_CHECK = (
    "cardinality(title_phrase_department_pos) = 0 OR "
    "(cardinality(title_phrase_department_pos) = cardinality(title_phrases) "
    "AND array_position(title_phrase_department_pos, NULL) IS NULL "
    "AND 0 <= ALL (title_phrase_department_pos) "
    "AND cardinality(named_title_department_ids) >= ALL (title_phrase_department_pos))"
)


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column(
            "title_phrase_department_pos",
            postgresql.ARRAY(sa.SmallInteger()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )
    op.add_column(TABLE, sa.Column("named_changed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(op.f("ck_insight_case_facts_phrase_pos"), TABLE, PHRASE_POS_CHECK)
    op.create_index(
        "ix_insight_case_facts_named_changed_at",
        TABLE,
        ["named_changed_at"],
        unique=False,
        postgresql_where=sa.text("named_changed_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_insight_case_facts_named_changed_at",
        table_name=TABLE,
        postgresql_where=sa.text("named_changed_at IS NOT NULL"),
    )
    op.drop_constraint(op.f("ck_insight_case_facts_phrase_pos"), TABLE, type_="check")
    op.drop_column(TABLE, "named_changed_at")
    op.drop_column(TABLE, "title_phrase_department_pos")
