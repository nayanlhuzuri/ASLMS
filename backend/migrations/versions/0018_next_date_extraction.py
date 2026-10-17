"""0018 next-date extraction: order readings, review statuses, next_dates checks, the review alert kind

Design `next-date-extraction` ("Data"; docs/schema/schema.md Groups 0, 6 and 7):
1. Enum values (autocommit block, as 0014 and 0017 did; unused inside this migration): `review_status` +
   `superseded`, + `expired` (system closures of pending rows).
2. `CREATE TYPE order_next_date_status` and the `orders` reading columns (`next_date_status` NOT NULL default
   `pending`, `next_date_found`, `next_date_rule`, `next_date_phrase`, `next_date_rules_version`,
   `next_date_read_at`); CHECKs `ck_orders_next_date_found`, `ck_orders_next_date_read`; partial index
   `ix_orders_next_date_pending`. Existing orders get `pending` from the default; the job reads them in batches.
3. `next_dates` CHECKs `ck_next_dates_manual_ref`, `ck_next_dates_pending_review`, `ck_next_dates_reviewed` and the
   partial index `ix_next_dates_pending`.
4. Reference rows, hard-coded (no application import, as 0016), `ON CONFLICT (code) DO NOTHING`: `ref_alert_kind`
   `next_date_review`; `ref_event_type` `next_date_reviewed`, `next_date_entered` (tracking card).
No grant change (`aslms_app` already has SELECT / INSERT / UPDATE on `orders` and `next_dates`). PostgreSQL cannot
drop enum values: the downgrade leaves the two review statuses in place (harmless, unused). The downgrade refuses
while any `next_dates` row of source `order_specific`, `order_period` or `manual` exists (legal-record history);
otherwise it drops what it added and deletes the three reference rows if unused.

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

STATUSES = ("pending", "specific", "period", "unclear", "none", "no_text")
ALERT_KINDS = (("next_date_review", "Next date to review", "normal", 120),)
EVENT_TYPES = (
    ("next_date_reviewed", "Next date reviewed", 350),
    ("next_date_entered", "Next date entered", 360),
)
READING_COLUMNS = (
    "next_date_read_at",
    "next_date_rules_version",
    "next_date_phrase",
    "next_date_rule",
    "next_date_found",
    "next_date_status",
)


def upgrade() -> None:
    # 1. new enum values (unused inside this migration)
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE review_status ADD VALUE IF NOT EXISTS 'superseded'")
        op.execute("ALTER TYPE review_status ADD VALUE IF NOT EXISTS 'expired'")

    # 2. the order readings
    sa.Enum(*STATUSES, name="order_next_date_status").create(op.get_bind(), checkfirst=True)
    op.add_column(
        "orders",
        sa.Column(
            "next_date_status",
            sa.Enum(*STATUSES, name="order_next_date_status", create_type=False),
            server_default="pending",
            nullable=False,
        ),
    )
    op.add_column("orders", sa.Column("next_date_found", sa.Date(), nullable=True))
    op.add_column("orders", sa.Column("next_date_rule", sa.String(length=40), nullable=True))
    op.add_column("orders", sa.Column("next_date_phrase", sa.String(length=400), nullable=True))
    op.add_column("orders", sa.Column("next_date_rules_version", sa.SmallInteger(), nullable=True))
    op.add_column("orders", sa.Column("next_date_read_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        op.f("ck_orders_next_date_found"),
        "orders",
        "(next_date_status IN ('specific', 'period')) = (next_date_found IS NOT NULL)",
    )
    op.create_check_constraint(
        op.f("ck_orders_next_date_read"),
        "orders",
        "(next_date_status = 'pending') = (next_date_read_at IS NULL)",
    )
    op.create_index(
        "ix_orders_next_date_pending",
        "orders",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("next_date_status = 'pending'"),
    )

    # 3. next_dates
    op.create_check_constraint(
        op.f("ck_next_dates_manual_ref"), "next_dates", "(source = 'manual') = (ref_no IS NOT NULL)"
    )
    op.create_check_constraint(
        op.f("ck_next_dates_pending_review"), "next_dates", "review_status <> 'pending' OR needs_review"
    )
    op.create_check_constraint(
        op.f("ck_next_dates_reviewed"),
        "next_dates",
        "review_status NOT IN ('confirmed', 'rejected') OR reviewed_at IS NOT NULL",
    )
    op.create_index(
        "ix_next_dates_pending",
        "next_dates",
        ["case_id", "next_date"],
        unique=False,
        postgresql_where=sa.text("review_status = 'pending'"),
    )

    # 4. reference rows
    bind = op.get_bind()
    for code, label, severity, sort_order in ALERT_KINDS:
        bind.execute(
            sa.text(
                "INSERT INTO ref_alert_kind (code, label, default_severity, sort_order, is_active) "
                "VALUES (:code, :label, :severity, :sort_order, true) ON CONFLICT (code) DO NOTHING"
            ),
            {"code": code, "label": label, "severity": severity, "sort_order": sort_order},
        )
    for code, label, sort_order in EVENT_TYPES:
        bind.execute(
            sa.text(
                "INSERT INTO ref_event_type (code, label, timeline_label, is_tracking_card, sort_order, is_active) "
                "VALUES (:code, :label, :label, true, :sort_order, true) ON CONFLICT (code) DO NOTHING"
            ),
            {"code": code, "label": label, "sort_order": sort_order},
        )


def downgrade() -> None:
    bind = op.get_bind()
    held = bind.execute(
        sa.text(
            "SELECT count(*) FROM next_dates WHERE source IN ('order_specific', 'order_period', 'manual')"
        )
    ).scalar()
    if held:
        raise RuntimeError(
            f"cannot downgrade 0018: {held} next_dates row(s) read from orders or entered by hand exist; "
            "the next-date history would be lost"
        )
    for code, _, _, _ in ALERT_KINDS:
        bind.execute(
            sa.text(
                "DELETE FROM ref_alert_kind WHERE code = :code "
                "AND NOT EXISTS (SELECT 1 FROM alerts WHERE kind = :code)"
            ),
            {"code": code},
        )
    for code, _, _ in EVENT_TYPES:
        bind.execute(
            sa.text(
                "DELETE FROM ref_event_type WHERE code = :code "
                "AND NOT EXISTS (SELECT 1 FROM events WHERE type::text = :code)"
            ),
            {"code": code},
        )
    op.drop_index("ix_next_dates_pending", table_name="next_dates")
    op.drop_constraint(op.f("ck_next_dates_reviewed"), "next_dates", type_="check")
    op.drop_constraint(op.f("ck_next_dates_pending_review"), "next_dates", type_="check")
    op.drop_constraint(op.f("ck_next_dates_manual_ref"), "next_dates", type_="check")
    op.drop_index("ix_orders_next_date_pending", table_name="orders")
    op.drop_constraint(op.f("ck_orders_next_date_read"), "orders", type_="check")
    op.drop_constraint(op.f("ck_orders_next_date_found"), "orders", type_="check")
    for column in READING_COLUMNS:
        op.drop_column("orders", column)
    sa.Enum(name="order_next_date_status").drop(op.get_bind(), checkfirst=True)
