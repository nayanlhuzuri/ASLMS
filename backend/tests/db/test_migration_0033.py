"""Migration 0033 (the merge of 0031 `session_timeout` and 0032 `assistant_ollama`): one head, no schema change;
upgrade to head, down to 0032 (only the merge step is undone: 0031 stays applied), up again."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory

from tests.db.conftest import alembic_config, head_revision, wipe_if_migrated

pytestmark = pytest.mark.migration_cycle


def _tables(conn) -> dict:
    q = lambda sql: conn.execute(sa.text(sql)).scalar()  # noqa: E731
    return {
        "sessions": q("SELECT to_regclass('user_sessions') IS NOT NULL"),
        "ollama_col": q(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'assistant_conversations' AND column_name = 'internal_included_at'"
        ),
    }


def test_single_head_is_the_merge(db_url):
    script = ScriptDirectory.from_config(alembic_config(db_url))
    assert script.get_heads() == ["0033"]
    assert set(script.get_revision("0033").down_revision) == {"0031", "0032"}


def test_migration_0033_cycles(db_url, engine):
    cfg = alembic_config(db_url)
    wipe_if_migrated(db_url)
    try:
        command.upgrade(cfg, "head")
        with engine.connect() as conn:
            assert _tables(conn) == {"sessions": True, "ollama_col": 1}
            assert (
                conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar() == head_revision()
            )
        command.downgrade(cfg, "0032")
        with engine.connect() as conn:
            assert _tables(conn) == {"sessions": True, "ollama_col": 1}
        command.upgrade(cfg, "head")
        with engine.connect() as conn:
            assert _tables(conn) == {"sessions": True, "ollama_col": 1}
    finally:
        command.upgrade(cfg, "head")
