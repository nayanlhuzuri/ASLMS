"""0032 assistant ollama: the `ollama` answer mode and the one-way switch for one case's internal records

Design `assistant-ollama` ("Data", round 1; docs/schema/schema.md "Phase 2 and 3 tables"). Main's head is 0030; row 169
(`session-timeout`, built on its own branch) holds 0031, so this is 0032 with down_revision 0030 while row 169 is
unmerged; the integrator re-points `down_revision` to 0031 if row 169 merges first. Written by hand: autogenerate does
not compare CHECK constraints or triggers, and the only column is one nullable timestamp.

1. `ck_assistant_messages_role_shape` is dropped and added again with `mode IN ('preview', 'sourcetrace', 'ollama')`.
2. `assistant_conversations.internal_included_at` (timestamptz NULL), with CHECK `ck_assistant_conversations_internal_case`
   (`internal_included_at IS NULL OR scope = 'case'`).
3. The BEFORE UPDATE trigger `assistant_conversations_internal_once` (function `aslms_assistant_internal_once`, owned by
   `aslms_owner` as the other trigger functions): once `internal_included_at` holds a value it never changes (set once,
   never cleared or moved). `aslms_app`'s grants are unchanged: its UPDATE on the table covers the column, and it still
   has no DELETE.

No new table, index, enum value, grant, `ref_*` code or function of `ref_function`. The `set_updated_at` trigger of
`assistant_conversations` already exists. The downgrade stops while any message has `mode = 'ollama'` or any
conversation has `internal_included_at` set (append-only or one-way rows: going back needs a restore, runbook section
6); otherwise it drops the trigger, its function, the CHECK and the column, and restores the old mode CHECK.

Revision ID: 0032
Revises: 0030
Create Date: 2026-10-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0032"
down_revision = "0030"
branch_labels = None
depends_on = None

OLD_SHAPE = (
    "(role = 'user' AND reply_to_id IS NULL AND mode IS NULL AND outcome IS NULL) OR "
    "(role = 'assistant' AND reply_to_id IS NOT NULL AND mode IN ('preview', 'sourcetrace') "
    "AND outcome IN ('answered', 'no_match', 'failed'))"
)
NEW_SHAPE = (
    "(role = 'user' AND reply_to_id IS NULL AND mode IS NULL AND outcome IS NULL) OR "
    "(role = 'assistant' AND reply_to_id IS NOT NULL AND mode IN ('preview', 'sourcetrace', 'ollama') "
    "AND outcome IN ('answered', 'no_match', 'failed'))"
)

ONCE_FUNCTION = """
CREATE OR REPLACE FUNCTION aslms_assistant_internal_once() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.internal_included_at IS NOT NULL
     AND NEW.internal_included_at IS DISTINCT FROM OLD.internal_included_at THEN
    RAISE EXCEPTION 'the internal-records switch of assistant conversation % is set once and never changes (ASLMS)',
      OLD.id USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END $$;
"""


def upgrade() -> None:
    # 1. the mode CHECK
    op.drop_constraint(op.f("ck_assistant_messages_role_shape"), "assistant_messages", type_="check")
    op.create_check_constraint(op.f("ck_assistant_messages_role_shape"), "assistant_messages", NEW_SHAPE)

    # 2. the switch column
    op.add_column(
        "assistant_conversations",
        sa.Column("internal_included_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_assistant_conversations_internal_case"),
        "assistant_conversations",
        "internal_included_at IS NULL OR scope = 'case'",
    )

    # 3. set once, never cleared or moved
    op.execute(ONCE_FUNCTION)
    op.execute("ALTER FUNCTION aslms_assistant_internal_once() OWNER TO aslms_owner")
    op.execute(
        "CREATE TRIGGER assistant_conversations_internal_once BEFORE UPDATE ON assistant_conversations "
        "FOR EACH ROW EXECUTE FUNCTION aslms_assistant_internal_once()"
    )


def downgrade() -> None:
    bind = op.get_bind()
    answers = bind.execute(sa.text("SELECT count(*) FROM assistant_messages WHERE mode = 'ollama'")).scalar()
    switched = bind.execute(
        sa.text("SELECT count(*) FROM assistant_conversations WHERE internal_included_at IS NOT NULL")
    ).scalar()
    if answers or switched:
        raise RuntimeError(
            f"cannot downgrade 0032: {answers} ollama answer(s) and {switched} conversation(s) with internal records "
            "switched on exist; they are append-only or one-way, so going back needs a restore (operations.md section 6)"
        )
    op.execute("DROP TRIGGER IF EXISTS assistant_conversations_internal_once ON assistant_conversations")
    op.execute("DROP FUNCTION IF EXISTS aslms_assistant_internal_once()")
    op.drop_constraint(
        op.f("ck_assistant_conversations_internal_case"), "assistant_conversations", type_="check"
    )
    op.drop_column("assistant_conversations", "internal_included_at")
    op.drop_constraint(op.f("ck_assistant_messages_role_shape"), "assistant_messages", type_="check")
    op.create_check_constraint(op.f("ck_assistant_messages_role_shape"), "assistant_messages", OLD_SHAPE)
