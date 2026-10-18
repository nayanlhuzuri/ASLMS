"""0019 safety fixes: the `search_rows` queue kind

Design `safety-fixes` ("Data"; docs/schema/schema.md, the `fetch_queue` paragraphs): `fetch_kind` gains
`search_rows` (ref `<napix_responses.id>`), the background storing of an advocate search's rows. It makes no NAPIX
call and is claimed only by the Celery task `aslms.store_search_rows`. No table or column is added and no grant
changes (`aslms_app` already has SELECT / INSERT / UPDATE on `fetch_queue` and INSERT / UPDATE on
`source_failures`). The value is added in an autocommit block, as 0014 and 0017 did. PostgreSQL cannot drop an enum
value: the downgrade leaves it in place (harmless, unused) and refuses while a `search_rows` row is pending or
running.

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE fetch_kind ADD VALUE IF NOT EXISTS 'search_rows'")


def downgrade() -> None:
    bind = op.get_bind()
    waiting = bind.execute(
        sa.text(
            "SELECT count(*) FROM fetch_queue "
            "WHERE kind::text = 'search_rows' AND status IN ('pending', 'running')"
        )
    ).scalar()
    if waiting:
        raise RuntimeError(
            f"cannot downgrade 0019: {waiting} search_rows queue row(s) are pending or running; "
            "let the store-search-rows task finish them first"
        )
