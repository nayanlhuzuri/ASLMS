"""0015 napix window: the user behind each NAPIX call

Design `napix-window` ("Data"; docs/schema/schema.md Group 9):
1. `napix_call_log.user_id` (uuid NULL, FK `fk_napix_call_log_user_id_users` → users RESTRICT): the person whose
   action caused the call; the partial index `ix_napix_call_log_user_called` (user_id, called_at) WHERE user_id IS
   NOT NULL.
2. `fetch_queue.requested_by` (uuid NULL, FK `fk_fetch_queue_requested_by_users` → users RESTRICT) and the CHECK
   `ck_fetch_queue_requested_by` (requested_by IS NULL OR lane = 'request'); every existing row passes (NULL).
No backfill: past rows stay NULL. No new type, table or grant (`aslms_app` keeps INSERT / SELECT on
`napix_call_log` and SELECT / INSERT / UPDATE on `fetch_queue`). The quota window itself is derived, not stored.
The downgrade drops the index, the CHECK and the two columns (log attributions, not legal records).

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. the call log
    op.add_column("napix_call_log", sa.Column("user_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_napix_call_log_user_id_users"),
        "napix_call_log",
        "users",
        ["user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_napix_call_log_user_called",
        "napix_call_log",
        ["user_id", "called_at"],
        unique=False,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )

    # 2. the queue
    op.add_column("fetch_queue", sa.Column("requested_by", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_fetch_queue_requested_by_users"),
        "fetch_queue",
        "users",
        ["requested_by"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        op.f("ck_fetch_queue_requested_by"), "fetch_queue", "requested_by IS NULL OR lane = 'request'"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_fetch_queue_requested_by"), "fetch_queue", type_="check")
    op.drop_constraint(op.f("fk_fetch_queue_requested_by_users"), "fetch_queue", type_="foreignkey")
    op.drop_column("fetch_queue", "requested_by")
    op.drop_index(
        "ix_napix_call_log_user_called",
        table_name="napix_call_log",
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.drop_constraint(op.f("fk_napix_call_log_user_id_users"), "napix_call_log", type_="foreignkey")
    op.drop_column("napix_call_log", "user_id")
