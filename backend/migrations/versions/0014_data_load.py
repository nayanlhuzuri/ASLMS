"""0014 data load: queue lanes, the versioned load settings, court-duplicate links

Design `data-load-console` ("Data"; docs/schema/schema.md Groups 3, 4 and 9):
1. Types `fetch_lane` (`request` / `daily` / `load`) and `load_order` (`cases_first` / `lists_first` /
   `cases_with_orders`), created once.
2. `fetch_queue.lane` (NOT NULL default `daily`), `fetch_queue.list_date`, the indexes `ix_fetch_queue_claim`
   (priority, created_at) WHERE status = 'pending' and `ix_fetch_queue_lane_list_date`; `napix_call_log.lane`.
3. `data_load_settings` (master, versioned) with its CHECKs, the partial unique index on `is_current`, the
   `set_updated_at()` trigger and the grants.
4. Data step, classifying the rows of the running historical load: `causelist_day` rows at priority 60 become `load`
   with `list_date = ref`; `dossier` rows at priority 45 become `load` with the earliest list date of an entry
   carrying that CNR (or that printed number for `<est>|<number>` refs); `order_pdf` rows whose CNR has a `load`
   dossier row follow as `load` with its `list_date`; pending load rows take the `cases_first` priorities (dossier
   44, day 46, order PDF 48); daily-lane pending `order_pdf` rows at 75 move to 40. Past `napix_call_log` rows keep
   `lane` NULL.
5. `link_kind` + `court_duplicate`, `link_source` + `dedupe` (autocommit block, after everything else; PostgreSQL
   cannot drop enum values, so the downgrade leaves them, unused).
The downgrade drops the table, the columns, the indexes and the two new types; priorities stay as changed.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

FETCH_LANE = ("request", "daily", "load")
LOAD_ORDER = ("cases_first", "lists_first", "cases_with_orders")


def upgrade() -> None:
    bind = op.get_bind()
    # 1. types
    postgresql.ENUM(*FETCH_LANE, name="fetch_lane").create(bind, checkfirst=False)
    postgresql.ENUM(*LOAD_ORDER, name="load_order").create(bind, checkfirst=False)
    lane_type = postgresql.ENUM(*FETCH_LANE, name="fetch_lane", create_type=False)
    order_type = postgresql.ENUM(*LOAD_ORDER, name="load_order", create_type=False)

    # 2. queue and call log columns
    op.add_column("fetch_queue", sa.Column("lane", lane_type, server_default="daily", nullable=False))
    op.add_column("fetch_queue", sa.Column("list_date", sa.Date(), nullable=True))
    op.create_index(
        "ix_fetch_queue_claim",
        "fetch_queue",
        ["priority", "created_at"],
        unique=False,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index("ix_fetch_queue_lane_list_date", "fetch_queue", ["lane", "list_date"], unique=False)
    op.add_column("napix_call_log", sa.Column("lane", lane_type, nullable=True))

    # 3. data_load_settings
    op.create_table(
        "data_load_settings",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("paused", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("load_order", order_type, server_default="cases_first", nullable=False),
        sa.Column("first_from", sa.Date(), nullable=True),
        sa.Column("first_to", sa.Date(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("is_current", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.CheckConstraint(
            "(first_from IS NULL) = (first_to IS NULL) AND (first_from IS NULL OR first_from <= first_to)",
            name=op.f("ck_data_load_settings_first"),
        ),
        sa.CheckConstraint("is_current = (valid_to IS NULL)", name=op.f("ck_data_load_settings_current")),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_data_load_settings_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_data_load_settings_updated_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_data_load_settings")),
        sa.UniqueConstraint("version", name=op.f("uq_data_load_settings_version")),
        comment="class=master",
    )
    op.create_index(
        "ix_data_load_settings_current",
        "data_load_settings",
        ["is_current"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )
    op.execute(
        "CREATE TRIGGER data_load_settings_updated_at BEFORE UPDATE ON data_load_settings "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )
    op.execute("GRANT ALL ON data_load_settings TO aslms_owner")
    op.execute("GRANT SELECT ON data_load_settings TO aslms_readonly")
    op.execute("GRANT SELECT, INSERT, UPDATE ON data_load_settings TO aslms_app")

    # 4. classify the running historical load
    op.execute(
        "UPDATE fetch_queue SET lane = 'load', list_date = CAST(ref AS date) "
        "WHERE kind = 'causelist_day' AND priority = 60 AND ref ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'"
    )
    op.execute(
        """
        UPDATE fetch_queue q SET lane = 'load', list_date = (
            SELECT min(cl.list_date)
            FROM causelist_entries e
            JOIN causelists cl ON cl.id = e.causelist_id
            LEFT JOIN cases c ON c.id = e.case_id
            WHERE CASE WHEN position('|' IN q.ref) > 0
                       THEN e.case_no_text = split_part(q.ref, '|', 2)
                       ELSE (e.cnr = q.ref OR c.cnr = q.ref) END
        )
        WHERE q.kind = 'dossier' AND q.priority = 45
        """
    )
    op.execute(
        """
        UPDATE fetch_queue o SET lane = 'load', list_date = d.list_date
        FROM fetch_queue d
        WHERE o.kind = 'order_pdf' AND d.kind = 'dossier' AND d.lane = 'load'
          AND d.ref = split_part(o.ref, '|', 1)
        """
    )
    op.execute(
        """
        UPDATE fetch_queue SET priority = CASE kind
            WHEN 'dossier' THEN 44 WHEN 'causelist_day' THEN 46 WHEN 'order_pdf' THEN 48 ELSE priority END
        WHERE lane = 'load' AND status = 'pending'
        """
    )
    op.execute(
        "UPDATE fetch_queue SET priority = 40 "
        "WHERE lane = 'daily' AND status = 'pending' AND kind = 'order_pdf' AND priority = 75"
    )

    # 5. new link values (unused inside this migration)
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE link_kind ADD VALUE IF NOT EXISTS 'court_duplicate'")
        op.execute("ALTER TYPE link_source ADD VALUE IF NOT EXISTS 'dedupe'")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS data_load_settings_updated_at ON data_load_settings")
    op.drop_index(
        "ix_data_load_settings_current",
        table_name="data_load_settings",
        postgresql_where=sa.text("is_current"),
    )
    op.drop_table("data_load_settings")
    op.drop_column("napix_call_log", "lane")
    op.drop_index("ix_fetch_queue_lane_list_date", table_name="fetch_queue")
    op.drop_index(
        "ix_fetch_queue_claim", table_name="fetch_queue", postgresql_where=sa.text("status = 'pending'")
    )
    op.drop_column("fetch_queue", "list_date")
    op.drop_column("fetch_queue", "lane")
    postgresql.ENUM(name="load_order").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="fetch_lane").drop(op.get_bind(), checkfirst=True)
