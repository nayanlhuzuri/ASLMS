"""Migration 0031 (design `session-timeout`, "Data"; the note's "0028" by build order): the enum
`session_end_reason`, the table `user_sessions` with its CHECKs, indexes, class comment, trigger and grants
(`aslms_app` SELECT / INSERT / UPDATE, never DELETE), and `refresh_tokens.session_id`; up, down, up."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic import command

from tests.db.conftest import alembic_config, head_revision, wipe_if_migrated

pytestmark = pytest.mark.migration_cycle


def _state(conn) -> dict:
    q = lambda sql: conn.execute(sa.text(sql)).scalar()  # noqa: E731
    return {
        "table": q("SELECT to_regclass('user_sessions') IS NOT NULL"),
        "enum": q("SELECT count(*) FROM pg_type WHERE typname = 'session_end_reason'"),
        "column": q(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'refresh_tokens' AND column_name = 'session_id'"
        ),
    }


def test_migration_0031_cycles(db_url, engine):
    cfg = alembic_config(db_url)
    wipe_if_migrated(db_url)
    try:
        command.downgrade(cfg, "0030")
        with engine.connect() as conn:
            assert _state(conn) == {"table": False, "enum": 0, "column": 0}
        command.upgrade(cfg, "0031")
        with engine.connect() as conn:
            assert _state(conn) == {"table": True, "enum": 1, "column": 1}
            labels = conn.execute(
                sa.text(
                    "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
                    "WHERE t.typname = 'session_end_reason' ORDER BY e.enumsortorder"
                )
            ).scalars()
            assert list(labels) == ["signed_out", "idle", "limit", "replaced", "ended"]
            priv = lambda p: conn.execute(  # noqa: E731
                sa.text("SELECT has_table_privilege('aslms_app', 'user_sessions', :p)"), {"p": p}
            ).scalar()
            assert priv("SELECT") and priv("INSERT") and priv("UPDATE")
            assert not priv("DELETE")
            assert conn.execute(
                sa.text("SELECT has_table_privilege('aslms_readonly', 'user_sessions', 'SELECT')")
            ).scalar()
            assert not conn.execute(
                sa.text("SELECT has_table_privilege('aslms_readonly', 'user_sessions', 'UPDATE')")
            ).scalar()
            assert (
                conn.execute(sa.text("SELECT obj_description('user_sessions'::regclass)")).scalar()
                == "class=derived"
            )
            names = set(
                conn.execute(
                    sa.text("SELECT conname FROM pg_constraint WHERE conrelid = 'user_sessions'::regclass")
                ).scalars()
            )
            assert {"ck_user_sessions_times", "ck_user_sessions_ended", "pk_user_sessions"} <= names
            indexes = set(
                conn.execute(
                    sa.text("SELECT indexname FROM pg_indexes WHERE tablename = 'user_sessions'")
                ).scalars()
            )
            assert {
                "ix_user_sessions_user_id",
                "ix_user_sessions_device_id",
                "ix_user_sessions_open",
            } <= indexes
            assert conn.execute(
                sa.text("SELECT count(*) FROM pg_trigger WHERE tgname = 'user_sessions_updated_at'")
            ).scalar()
            assert conn.execute(
                sa.text("SELECT count(*) FROM pg_indexes WHERE indexname = 'ix_refresh_tokens_session_id'")
            ).scalar()
        command.downgrade(cfg, "0030")
        with engine.connect() as conn:
            assert _state(conn) == {"table": False, "enum": 0, "column": 0}
    finally:
        command.upgrade(cfg, "head")
    with engine.connect() as conn:
        assert conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar() == head_revision()
        assert _state(conn) == {"table": True, "enum": 1, "column": 1}
