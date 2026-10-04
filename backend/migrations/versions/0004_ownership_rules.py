"""0004 ownership rules: scoring settings, rule-weight overrides, ownership uniqueness, allotment columns

Design `recommend-and-claim` (docs/schema/schema.md Group 5, as built): the versioned `scoring_settings`
master; rule weights become NULL-able overrides of the kind's setting; partial unique indexes for one active
primary owner per case, one active row per (case, office), one active recommendation per (case, office) and
one open transfer per case; a CHECK that a primary ownership row is never released; `case_ownership` gains
`allotted_at`, `allotted_by_user_id`, `release_reason`; `ownership_transfers` gains `stay_as_watcher` and
`decision_note`. New codes in `ref_permission` and `ref_event_type` are seed rows. No native enum changes.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

# table -> the server default the weight column had before this revision
RULE_WEIGHTS = {
    "counsel_codes": "0.950",
    "office_keywords": "0.400",
    "office_name_patterns": "0.800",
    "office_watchlist": "0.750",
}
WEIGHT_CHECK = "weight IS NULL OR (weight > 0 AND weight <= 1)"


def upgrade() -> None:
    op.create_table(
        "scoring_settings",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("weight_counsel_code", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("weight_name_pattern", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("weight_watchlist", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("weight_linked_case", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("weight_keyword", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("threshold_strong", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("threshold_possible", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("is_current", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.CheckConstraint("is_current = (valid_to IS NULL)", name=op.f("ck_scoring_settings_current")),
        sa.CheckConstraint(
            "threshold_possible > 0 AND threshold_possible < threshold_strong AND threshold_strong <= 1",
            name=op.f("ck_scoring_settings_thresholds"),
        ),
        sa.CheckConstraint(
            "weight_counsel_code > 0 AND weight_counsel_code <= 1 AND "
            "weight_name_pattern > 0 AND weight_name_pattern <= 1 AND "
            "weight_watchlist > 0 AND weight_watchlist <= 1 AND "
            "weight_linked_case > 0 AND weight_linked_case <= 1 AND "
            "weight_keyword > 0 AND weight_keyword <= 1",
            name=op.f("ck_scoring_settings_weights"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_scoring_settings_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_scoring_settings_updated_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scoring_settings")),
        sa.UniqueConstraint("version", name=op.f("uq_scoring_settings_version")),
        comment="class=master",
    )
    op.create_index(
        "ix_scoring_settings_current",
        "scoring_settings",
        ["is_current"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )
    op.execute(
        "CREATE TRIGGER scoring_settings_updated_at BEFORE UPDATE ON scoring_settings "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )
    op.execute("GRANT ALL ON scoring_settings TO aslms_owner")
    op.execute("GRANT SELECT ON scoring_settings TO aslms_readonly")
    op.execute("GRANT SELECT, INSERT, UPDATE ON scoring_settings TO aslms_app")

    # rule weights: NULL = the kind's setting; a value is an override
    for table, old_default in RULE_WEIGHTS.items():
        op.alter_column(
            table,
            "weight",
            existing_type=sa.Numeric(precision=4, scale=3),
            server_default=None,
            nullable=True,
        )
        op.execute(f"UPDATE {table} SET weight = NULL WHERE weight = {old_default}")
        op.create_check_constraint(op.f(f"ck_{table}_weight"), table, WEIGHT_CHECK)

    op.create_check_constraint(
        op.f("ck_recommendations_score_range"), "recommendations", "score >= 0 AND score <= 1"
    )
    op.create_index(
        "ix_recommendations_active",
        "recommendations",
        ["case_id", "office_id"],
        unique=True,
        postgresql_where=sa.text("status = 'recommended'"),
    )

    op.add_column("case_ownership", sa.Column("allotted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("case_ownership", sa.Column("allotted_by_user_id", sa.UUID(), nullable=True))
    op.add_column("case_ownership", sa.Column("release_reason", sa.Text(), nullable=True))
    op.create_index(
        op.f("ix_case_ownership_allotted_by_user_id"), "case_ownership", ["allotted_by_user_id"], unique=False
    )
    op.create_foreign_key(
        op.f("fk_case_ownership_allotted_by_user_id_users"),
        "case_ownership",
        "users",
        ["allotted_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_case_ownership_active_primary",
        "case_ownership",
        ["case_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active' AND role = 'primary'"),
    )
    op.create_index(
        "ix_case_ownership_active_office",
        "case_ownership",
        ["case_id", "office_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_check_constraint(
        op.f("ck_case_ownership_release_watcher"),
        "case_ownership",
        "status <> 'released' OR role = 'watcher'",
    )

    op.add_column(
        "ownership_transfers",
        sa.Column("stay_as_watcher", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("ownership_transfers", sa.Column("decision_note", sa.Text(), nullable=True))
    op.create_index(
        "ix_ownership_transfers_open",
        "ownership_transfers",
        ["case_id"],
        unique=True,
        postgresql_where=sa.text("status = 'requested'"),
    )


def downgrade() -> None:
    op.drop_index("ix_ownership_transfers_open", table_name="ownership_transfers")
    op.drop_column("ownership_transfers", "decision_note")
    op.drop_column("ownership_transfers", "stay_as_watcher")

    op.drop_constraint(op.f("ck_case_ownership_release_watcher"), "case_ownership", type_="check")
    op.drop_index("ix_case_ownership_active_office", table_name="case_ownership")
    op.drop_index("ix_case_ownership_active_primary", table_name="case_ownership")
    op.drop_constraint(
        op.f("fk_case_ownership_allotted_by_user_id_users"), "case_ownership", type_="foreignkey"
    )
    op.drop_index(op.f("ix_case_ownership_allotted_by_user_id"), table_name="case_ownership")
    op.drop_column("case_ownership", "release_reason")
    op.drop_column("case_ownership", "allotted_by_user_id")
    op.drop_column("case_ownership", "allotted_at")

    op.drop_index("ix_recommendations_active", table_name="recommendations")
    op.drop_constraint(op.f("ck_recommendations_score_range"), "recommendations", type_="check")

    for table, old_default in RULE_WEIGHTS.items():
        op.drop_constraint(op.f(f"ck_{table}_weight"), table, type_="check")
        op.execute(f"UPDATE {table} SET weight = {old_default} WHERE weight IS NULL")
        op.alter_column(
            table,
            "weight",
            existing_type=sa.Numeric(precision=4, scale=3),
            server_default=sa.text(old_default),
            nullable=False,
        )

    op.execute("DROP TRIGGER IF EXISTS scoring_settings_updated_at ON scoring_settings")
    op.drop_index("ix_scoring_settings_current", table_name="scoring_settings")
    op.drop_table("scoring_settings")
