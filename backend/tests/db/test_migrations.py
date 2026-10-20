"""Migration 0001 builds the approved schema and can be undone: upgrade → downgrade → upgrade, then the
database agrees with the models (no autogenerate diff), the standard's functions, triggers, comments and
roles exist, and the append-only trigger bites."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext

import aslms.domain  # noqa: F401
from aslms.db.base import APPEND_ONLY_TABLES, MUTABLE_TABLES, Base
from tests.db.conftest import alembic_config, wipe_if_migrated


def _scalar(engine: sa.Engine, sql: str):
    with engine.connect() as conn:
        return conn.execute(sa.text(sql)).scalar()


@pytest.mark.migration_cycle
def test_upgrade_downgrade_upgrade(db_url: str):
    cfg = alembic_config(db_url)
    wipe_if_migrated(db_url)  # the downgrades refuse to strip populated tables
    command.downgrade(cfg, "base")
    engine = sa.create_engine(db_url, poolclass=sa.pool.NullPool)
    assert (
        _scalar(
            engine,
            "select count(*) from pg_tables where schemaname='public' and tablename <> 'alembic_version'",
        )
        == 0
    )
    assert _scalar(engine, "select count(*) from pg_type where typtype='e'") == 0
    command.upgrade(cfg, "head")
    assert (
        _scalar(engine, "select count(*) from pg_tables where schemaname='public'")
        == len(Base.metadata.tables) + 1
    )
    command.downgrade(cfg, "base")
    assert (
        _scalar(
            engine,
            "select count(*) from pg_tables where schemaname='public' and tablename <> 'alembic_version'",
        )
        == 0
    )
    assert (
        _scalar(
            engine,
            "select count(*) from pg_proc where proname in ('uuid_generate_v7','set_updated_at','aslms_forbid_change')",
        )
        == 0
    )
    command.upgrade(cfg, "head")
    engine.dispose()


def test_database_matches_the_models(engine: sa.Engine):
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True, "compare_server_default": True})
        diff = compare_metadata(ctx, Base.metadata)
    # a non-native Enum compares as VARCHAR; everything else must agree
    real = [d for d in diff if not (d[0] == "modify_type" and isinstance(d[-1], sa.Enum))]
    assert real == [], real


def test_standard_objects_exist(engine: sa.Engine):
    n_tables = len(Base.metadata.tables)
    assert (
        _scalar(
            engine,
            "select count(*) from pg_description d join pg_class c on c.oid=d.objoid where c.relkind='r' and d.description like 'class=%'",
        )
        == n_tables
    )
    assert _scalar(
        engine, "select count(*) from pg_trigger where not tgisinternal and tgname like '%_updated_at'"
    ) == len(MUTABLE_TABLES)
    assert _scalar(
        engine, "select count(*) from pg_trigger where not tgisinternal and tgname like '%_append_only'"
    ) == len(APPEND_ONLY_TABLES)
    assert (
        _scalar(
            engine,
            "select count(*) from pg_roles where rolname in ('aslms_owner','aslms_app','aslms_readonly')",
        )
        == 3
    )
    assert _scalar(engine, "select has_table_privilege('aslms_app','cases','DELETE')") is False
    assert _scalar(engine, "select has_table_privilege('aslms_app','otp_codes','DELETE')") is True
    assert _scalar(engine, "select has_table_privilege('aslms_app','audit_log','UPDATE')") is False
    assert _scalar(engine, "select has_table_privilege('aslms_readonly','cases','SELECT')") is True
    assert _scalar(engine, "select has_table_privilege('aslms_readonly','cases','INSERT')") is False


def test_uuid_v7_is_time_ordered(engine: sa.Engine):
    # v7 orders by millisecond; two calls inside one millisecond share the prefix and differ by random bits,
    # so the second value is taken after a 2 ms pause.
    with engine.connect() as conn:
        a = conn.execute(sa.text("select uuid_generate_v7()")).scalar()
        b = conn.execute(sa.text("select pg_sleep(0.002), uuid_generate_v7()")).one()[1]
    assert str(a) < str(b)
    assert str(a)[14] == "7"


def test_append_only_trigger_blocks_update_and_delete(session):
    session.execute(sa.text("insert into audit_log (action, entity_type) values ('test', 'none')"))
    with pytest.raises(sa.exc.DBAPIError, match="append-only"):
        session.execute(sa.text("update audit_log set action = 'x'"))
    session.rollback()
    session.execute(sa.text("insert into audit_log (action, entity_type) values ('test', 'none')"))
    with pytest.raises(sa.exc.DBAPIError, match="append-only"):
        session.execute(sa.text("delete from audit_log"))
    session.rollback()


def test_updated_at_trigger(session):
    """The trigger overrides whatever updated_at the client sends (now() is the transaction time, so the
    test writes an old value and expects the trigger to replace it)."""
    session.execute(sa.text("insert into acts (name) values ('Test Act')"))
    session.execute(
        sa.text("update acts set name = 'Test Act 2', updated_at = '2000-01-01' where name = 'Test Act'")
    )
    after = session.execute(sa.text("select updated_at from acts where name = 'Test Act 2'")).scalar()
    assert after.year >= 2026
