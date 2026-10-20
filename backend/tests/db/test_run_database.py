"""Design github-and-ci, decision 4: each session works in its own database, the sweep drops only stale run
databases of killed runs, and the cluster roles exist before the first migration."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url

from tests.db import conftest as c
from tests.db import rundb


def _exists(conn: sa.Connection, name: str) -> bool:
    return bool(conn.execute(sa.text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}).scalar())


@pytest.fixture()
def admin(db_url: str):
    eng = rundb.autocommit_engine(rundb.maintenance_url(c.BASE_URL))
    with eng.connect() as conn:
        yield conn
    eng.dispose()


@pytest.mark.skipif(not c.PER_RUN, reason="ASLMS_TEST_DB_PER_RUN=0 uses the named database")
def test_session_uses_its_own_database(db_url: str, admin):
    name = make_url(db_url).database
    base = c.BASE_URL.database or "aslms_test"
    assert name != base
    assert rundb.run_name_pattern(base).match(name)
    assert _exists(admin, name)
    eng = sa.create_engine(db_url, poolclass=sa.pool.NullPool)
    try:
        with eng.connect() as conn:
            assert conn.execute(sa.text("SELECT current_database()")).scalar() == name
    finally:
        eng.dispose()


def test_sweep_drops_stale_and_keeps_fresh_and_foreign_names(admin):
    base = c.BASE_URL.database or "aslms_test"
    now = datetime.now(UTC)
    stale = rundb.run_database_name(base, now - timedelta(days=2), secrets.token_hex(3))
    fresh = rundb.run_database_name(base, now - timedelta(hours=1), secrets.token_hex(3))
    foreign = f"{rundb.name_base(base)}_keep_{secrets.token_hex(3)}"
    created = [stale, fresh, foreign]
    try:
        for name in created:
            rundb.create_database(admin, name)
        rundb.sweep_stale(admin, base)
        # another run's sweep may have dropped the stale one first; either way it is gone
        assert not _exists(admin, stale)
        assert _exists(admin, fresh)
        assert _exists(admin, foreign)
    finally:
        for name in created:
            admin.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}"'))


def test_sweep_leaves_a_stale_database_with_a_session(admin):
    base = c.BASE_URL.database or "aslms_test"
    busy = rundb.run_database_name(base, datetime.now(UTC) - timedelta(days=3), secrets.token_hex(3))
    rundb.create_database(admin, busy)
    holder = sa.create_engine(c.BASE_URL.set(database=busy), poolclass=sa.pool.NullPool)
    try:
        with holder.connect() as conn:
            conn.execute(sa.text("SELECT 1"))
            assert busy not in rundb.sweep_stale(admin, base)
            assert _exists(admin, busy)
    finally:
        holder.dispose()
        admin.execute(sa.text(f'DROP DATABASE IF EXISTS "{busy}"'))


def test_cluster_roles_exist_after_db_url(admin):
    got = set(
        admin.execute(
            sa.text("SELECT rolname FROM pg_roles WHERE rolname = ANY(:r)"), {"r": list(rundb.ROLES)}
        )
        .scalars()
        .all()
    )
    assert got == set(rundb.ROLES)


def test_cluster_lock_is_reentrant_and_released(admin):
    with c.cluster_lock(), c.cluster_lock():
        # another connection cannot take it while this run holds it (nested entry did not wait on itself)
        took = admin.execute(
            sa.text("SELECT pg_try_advisory_lock(hashtext(:k))"), {"k": rundb.LOCK_KEY}
        ).scalar()
        assert took is False
    assert getattr(rundb._lock_state, "depth", 0) == 0
