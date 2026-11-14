"""0037 assistant my_work: the sidebar Assistant's My Work scope

Design `assistant-ollama-work` ("Data"; docs/schema/schema.md, the `assistant_conversations` and `assistant_messages`
paragraphs): hand-written, the next free number after 0036 (`offices-import`). One change, in an autocommit block as
0017, 0023 and 0024 do: `assistant_scope` gains `my_work` (the domain enum `AssistantScope.MY_WORK`).

No other change: no table, column, index, grant, trigger, `ref_*` code or function. The existing CHECK
`ck_assistant_conversations_case_scope` keeps `case_id` null for `my_work`, `ck_assistant_conversations_internal_case`
keeps `internal_included_at` null, and the mode CHECK of `assistant_messages` already admits `ollama` and `preview`.
A My Work answer is stored with connector `work` and `work_row` citations (jsonb, no schema change).

The downgrade stops while any conversation has scope `my_work` (a restore is needed, runbook section 6). PostgreSQL
cannot drop an enum value, so `my_work` itself stays after a downgrade (harmless, unused).

Revision ID: 0037
Revises: 0036
Create Date: 2026-11-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE assistant_scope ADD VALUE IF NOT EXISTS 'my_work'")


def downgrade() -> None:
    bind = op.get_bind()
    work = bind.execute(
        sa.text("SELECT count(*) FROM assistant_conversations WHERE scope::text = 'my_work'")
    ).scalar()
    if work:
        raise RuntimeError(
            f"cannot downgrade 0037: {work} my_work conversation(s) exist; the conversations would lose their "
            "record (restore from a backup, runbook section 6). The enum value my_work cannot be dropped and stays."
        )
    # nothing else to undo: PostgreSQL cannot drop the enum value `my_work`, which stays unused
