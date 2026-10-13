"""0017 department discovery: discoverable rules, discovery terms and hits, the discovery lane

Design `department-discovery` ("Data"; docs/schema/schema.md Groups 3, 5 and 9):
1. `office_keywords.discover` and `office_name_patterns.discover` (boolean NOT NULL default false); CHECK
   `ck_office_name_patterns_discover` (`kind <> 'regex' OR NOT discover`). Data step: existing rules whose text is
   discoverable (3-200 characters of `[A-Z0-9 .,'&()/-]`; patterns of kind `exact` / `prefix` only) get `discover =
   true` (decision 1: default on).
2. `discovery_terms` (derived): one row per distinct discoverable text, CHECK `ck_discovery_terms_term`.
3. `discovery_hits` (derived): one row per (term, case) a search returned; FKs RESTRICT; index on case_id.
   Both tables: the `set_updated_at()` trigger and the grants (`aslms_app` SELECT / INSERT / UPDATE, no DELETE).
4. Enum values (autocommit block, after everything else, as 0014 did): `fetch_kind` + `party_search`, `fetch_lane` +
   `discovery` BEFORE `load` (precedence request < daily < discovery < load), `recommendation_origin` + `discovery`.
PostgreSQL cannot drop enum values: the downgrade leaves them in place (harmless, unused). The downgrade refuses while
a `party_search` row is pending or running; otherwise it drops the tables, the CHECK and the columns.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

TERM_SQL = "^[A-Z0-9 .,''&()/-]{3,200}$"  # SQL literal form (quote doubled)
TABLES = ("discovery_terms", "discovery_hits")


def upgrade() -> None:
    # 1. the rule columns
    op.add_column(
        "office_keywords",
        sa.Column("discover", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "office_name_patterns",
        sa.Column("discover", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_office_name_patterns_discover"), "office_name_patterns", "kind <> 'regex' OR NOT discover"
    )
    op.execute(f"UPDATE office_keywords SET discover = true WHERE keyword ~ '{TERM_SQL}'")
    op.execute(
        f"UPDATE office_name_patterns SET discover = true WHERE kind <> 'regex' AND pattern ~ '{TERM_SQL}'"
    )

    # 2. discovery_terms
    op.create_table(
        "discovery_terms",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("term", sa.String(length=200), nullable=False),
        sa.Column("full_sweep_queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recent_sweep_queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_searched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("searches_done", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("cases_found", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(f"term ~ '{TERM_SQL}'", name=op.f("ck_discovery_terms_term")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_discovery_terms")),
        sa.UniqueConstraint("term", name=op.f("uq_discovery_terms_term")),
        comment="class=derived",
    )

    # 3. discovery_hits
    op.create_table(
        "discovery_hits",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("term_id", sa.UUID(), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("reg_year", sa.Integer(), nullable=False),
        sa.Column(
            "first_found_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "last_found_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_discovery_hits_case_id_cases"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["term_id"],
            ["discovery_terms.id"],
            name=op.f("fk_discovery_hits_term_id_discovery_terms"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_discovery_hits")),
        sa.UniqueConstraint("term_id", "case_id", name=op.f("uq_discovery_hits_term_id_case_id")),
        comment="class=derived",
    )
    op.create_index(op.f("ix_discovery_hits_case_id"), "discovery_hits", ["case_id"], unique=False)
    for table in TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_updated_at BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
        )
        op.execute(f"GRANT ALL ON {table} TO aslms_owner")
        op.execute(f"GRANT SELECT ON {table} TO aslms_readonly")
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO aslms_app")

    # 4. new enum values (unused inside this migration)
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE fetch_kind ADD VALUE IF NOT EXISTS 'party_search'")
        op.execute("ALTER TYPE fetch_lane ADD VALUE IF NOT EXISTS 'discovery' BEFORE 'load'")
        op.execute("ALTER TYPE recommendation_origin ADD VALUE IF NOT EXISTS 'discovery'")


def downgrade() -> None:
    bind = op.get_bind()
    waiting = bind.execute(
        sa.text(
            "SELECT count(*) FROM fetch_queue "
            "WHERE kind::text = 'party_search' AND status IN ('pending', 'running')"
        )
    ).scalar()
    if waiting:
        raise RuntimeError(
            f"cannot downgrade 0017: {waiting} party_search queue row(s) are pending or running; "
            "let them finish or stop discovery first"
        )
    for table in reversed(TABLES):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_updated_at ON {table}")
    op.drop_index(op.f("ix_discovery_hits_case_id"), table_name="discovery_hits")
    op.drop_table("discovery_hits")
    op.drop_table("discovery_terms")
    op.drop_constraint(op.f("ck_office_name_patterns_discover"), "office_name_patterns", type_="check")
    op.drop_column("office_name_patterns", "discover")
    op.drop_column("office_keywords", "discover")
