"""Migration 0020 (design deployment-checklist, Part B, decision 27 and "Data"): `aslms_readonly` becomes a member of
the predefined role `pg_monitor` (statistics only, still no write), and the downgrade revokes it."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import command

from tests.db.conftest import alembic_config


def test_readonly_role_is_a_pg_monitor_member(engine):
    with engine.connect() as conn:
        assert conn.execute(sa.text("select pg_has_role('aslms_readonly', 'pg_monitor', 'MEMBER')")).scalar()
        # still no write on a table
        assert not conn.execute(
            sa.text("select has_table_privilege('aslms_readonly', 'public.cases', 'INSERT')")
        ).scalar()


def test_0020_upgrade_and_downgrade(db_url, engine):
    cfg = alembic_config(db_url)

    def member() -> bool:
        with engine.connect() as conn:
            return bool(
                conn.execute(sa.text("select pg_has_role('aslms_readonly', 'pg_monitor', 'MEMBER')")).scalar()
            )

    command.downgrade(cfg, "0019")
    try:
        assert member() is False
    finally:
        command.upgrade(cfg, "head")
    assert member() is True
    command.downgrade(cfg, "0019")
    command.upgrade(cfg, "head")
    assert member() is True
