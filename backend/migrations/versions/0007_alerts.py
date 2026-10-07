"""0007 alerts: the office addressed, the alert's data and closure, the notification outbox and the digest's
sending state

Design `alerts-notifications` (docs/schema/schema.md Group 7, "Data"):
- `alerts`: `office_id` (→ offices RESTRICT; the office the alert is addressed to — the owning department, the
  recommended department, the request's receiving office, the transfer's department; the table is empty, so
  NOT NULL needs no default), `data` jsonb (links and dates), `closed_at`, `closed_by_user_id` (→ users SET
  NULL). CHECKs `ck_alerts_closed` (done / expired ⇔ closed_at) and `ck_alerts_acknowledged`. Indexes
  `ix_alerts_case_status`, partial `ix_alerts_open_kind` (open and acknowledged alerts by kind and due date),
  `ix_alerts_office_id`, `ix_alerts_closed_by_user_id`.
- `notifications`: `severity` (the level notified; an upgrade to critical notifies again), `attempts`,
  `next_attempt_at`. CHECK `ck_notifications_read` (`read` only for an in-app row with `read_at`). Indexes
  `ix_notifications_user_inbox`, partial `ix_notifications_outbox` (e-mail rows still to send).
- `digests`: `status`, `item_count`, `attempts`, `next_attempt_at`, `error`, `body`.
No new table or enum type (`alert_severity` and `notification_status` exist since 0001; the columns reuse
them with `create_type=False`); the two new `ref_alert_kind` codes (`ownership`, `new_document`) are seed
rows. The 0001 grants cover the columns and the indexes. The downgrade drops what this revision added; the
tables are empty before and after (no legal record is touched).

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

ALERT_SEVERITY = postgresql.ENUM("critical", "high", "normal", name="alert_severity", create_type=False)
NOTIFICATION_STATUS = postgresql.ENUM(
    "queued", "sent", "failed", "read", name="notification_status", create_type=False
)
# short names; the metadata naming convention makes them ck_<table>_<name>
ALERT_CHECKS = {
    "closed": "(status IN ('done', 'expired')) = (closed_at IS NOT NULL)",
    "acknowledged": "status <> 'acknowledged' OR acknowledged_at IS NOT NULL",
}
NOTIFICATION_CHECKS = {"read": "status <> 'read' OR (channel = 'in_app' AND read_at IS NOT NULL)"}
OPEN_KIND_WHERE = sa.text("status IN ('open', 'acknowledged')")
OUTBOX_WHERE = sa.text("channel = 'email' AND status IN ('queued', 'failed')")


def upgrade() -> None:
    # alerts
    op.add_column("alerts", sa.Column("office_id", sa.UUID(), nullable=False))
    op.add_column(
        "alerts",
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
    )
    op.add_column("alerts", sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("alerts", sa.Column("closed_by_user_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_alerts_office_id_offices"), "alerts", "offices", ["office_id"], ["id"], ondelete="RESTRICT"
    )
    op.create_foreign_key(
        op.f("fk_alerts_closed_by_user_id_users"),
        "alerts",
        "users",
        ["closed_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_alerts_office_id"), "alerts", ["office_id"], unique=False)
    op.create_index(op.f("ix_alerts_closed_by_user_id"), "alerts", ["closed_by_user_id"], unique=False)
    op.create_index("ix_alerts_case_status", "alerts", ["case_id", "status"], unique=False)
    op.create_index(
        "ix_alerts_open_kind", "alerts", ["kind", "due_at"], unique=False, postgresql_where=OPEN_KIND_WHERE
    )
    for name, expr in ALERT_CHECKS.items():
        op.create_check_constraint(name, "alerts", expr)
    # notifications
    op.add_column(
        "notifications", sa.Column("severity", ALERT_SEVERITY, server_default="normal", nullable=False)
    )
    op.add_column(
        "notifications",
        sa.Column("attempts", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column("notifications", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_notifications_user_inbox", "notifications", ["user_id", "channel", "status"], unique=False
    )
    op.create_index(
        "ix_notifications_outbox",
        "notifications",
        ["next_attempt_at"],
        unique=False,
        postgresql_where=OUTBOX_WHERE,
    )
    for name, expr in NOTIFICATION_CHECKS.items():
        op.create_check_constraint(name, "notifications", expr)
    # digests
    op.add_column(
        "digests", sa.Column("status", NOTIFICATION_STATUS, server_default="queued", nullable=False)
    )
    op.add_column(
        "digests", sa.Column("item_count", sa.Integer(), server_default=sa.text("0"), nullable=False)
    )
    op.add_column(
        "digests", sa.Column("attempts", sa.SmallInteger(), server_default=sa.text("0"), nullable=False)
    )
    op.add_column("digests", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("digests", sa.Column("error", sa.Text(), nullable=True))
    op.add_column("digests", sa.Column("body", sa.Text(), nullable=True))


def downgrade() -> None:
    for col in ("body", "error", "next_attempt_at", "attempts", "item_count", "status"):
        op.drop_column("digests", col)
    for name in NOTIFICATION_CHECKS:
        op.drop_constraint(name, "notifications", type_="check")
    op.drop_index("ix_notifications_outbox", table_name="notifications", postgresql_where=OUTBOX_WHERE)
    op.drop_index("ix_notifications_user_inbox", table_name="notifications")
    for col in ("next_attempt_at", "attempts", "severity"):
        op.drop_column("notifications", col)
    for name in ALERT_CHECKS:
        op.drop_constraint(name, "alerts", type_="check")
    op.drop_index("ix_alerts_open_kind", table_name="alerts", postgresql_where=OPEN_KIND_WHERE)
    op.drop_index("ix_alerts_case_status", table_name="alerts")
    op.drop_index(op.f("ix_alerts_closed_by_user_id"), table_name="alerts")
    op.drop_index(op.f("ix_alerts_office_id"), table_name="alerts")
    op.drop_constraint(op.f("fk_alerts_closed_by_user_id_users"), "alerts", type_="foreignkey")
    op.drop_constraint(op.f("fk_alerts_office_id_offices"), "alerts", type_="foreignkey")
    for col in ("closed_by_user_id", "closed_at", "data", "office_id"):
        op.drop_column("alerts", col)
