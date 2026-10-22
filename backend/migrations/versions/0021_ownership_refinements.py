"""0021 ownership refinements: the `claimed_elsewhere` recommendation status and the `recommendation_closed` event type

Design `ownership-refinements`, decision 16 and "Data"; docs/schema/schema.md, Group 5 row `recommendations` and Group 0
row `ref_event_type`. Autogenerate found nothing (an added enum value and a reference row are not compared):
1. Autocommit block, as 0014, 0017 and 0018 did: `recommendation_status` + `claimed_elsewhere` (unused inside this
   migration).
2. `ref_event_type` `recommendation_closed` ("Recommendation closed", not on the tracking card, sort 370), hard-coded
   with no application import, as 0016 and 0018, `ON CONFLICT (code) DO NOTHING`.
No table, column or index is added; no grant change (`aslms_app` already has SELECT / INSERT / UPDATE on
`recommendations` and INSERT on `events`). The downgrade refuses while any recommendation is `claimed_elsewhere`
(legal-record history the old code cannot read); otherwise it deletes the reference row if no event uses it.
PostgreSQL cannot drop an enum value, so `claimed_elsewhere` stays (harmless, unused).

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

EVENT_TYPES = (("recommendation_closed", "Recommendation closed", 370),)


def upgrade() -> None:
    # 1. the new status (unused inside this migration)
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE recommendation_status ADD VALUE IF NOT EXISTS 'claimed_elsewhere'")

    # 2. the reference row
    bind = op.get_bind()
    for code, label, sort_order in EVENT_TYPES:
        bind.execute(
            sa.text(
                "INSERT INTO ref_event_type (code, label, timeline_label, is_tracking_card, sort_order, is_active) "
                "VALUES (:code, :label, :label, false, :sort_order, true) ON CONFLICT (code) DO NOTHING"
            ),
            {"code": code, "label": label, "sort_order": sort_order},
        )


def downgrade() -> None:
    bind = op.get_bind()
    held = bind.execute(
        sa.text("SELECT count(*) FROM recommendations WHERE status::text = 'claimed_elsewhere'")
    ).scalar()
    if held:
        raise RuntimeError(
            f"cannot downgrade 0021: {held} recommendation(s) are claimed_elsewhere; "
            "that ownership history would be unreadable"
        )
    for code, _, _ in EVENT_TYPES:
        bind.execute(
            sa.text(
                "DELETE FROM ref_event_type WHERE code = :code "
                "AND NOT EXISTS (SELECT 1 FROM events WHERE type::text = :code)"
            ),
            {"code": code},
        )
