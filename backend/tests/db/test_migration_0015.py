"""Migration 0015 (design `napix-window`, "Data"): `napix_call_log.user_id` and `fetch_queue.requested_by` are nullable
with RESTRICT foreign keys to users, the CHECK `ck_fetch_queue_requested_by` and the partial index
`ix_napix_call_log_user_called` exist; the downgrade drops them and keeps every row; the database matches the models
at head."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.orm import sessionmaker

from aslms.db.base import Base
from aslms.services.seed import seed_all
from tests.db.conftest import alembic_config, wipe_if_migrated

pytestmark = pytest.mark.migration_cycle

COLUMNS = {("napix_call_log", "user_id"), ("fetch_queue", "requested_by")}
FKS = {"fk_napix_call_log_user_id_users", "fk_fetch_queue_requested_by_users"}


def _columns(engine) -> dict[tuple[str, str], str]:
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text(
                "select table_name, column_name, is_nullable from information_schema.columns "
                "where (table_name, column_name) in (('napix_call_log', 'user_id'), ('fetch_queue', 'requested_by'))"
            )
        ).all()
    return {(t, c): n for t, c, n in rows}


def _fks(engine) -> dict[str, str]:
    """FK name → its delete rule (`r` = RESTRICT)."""
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text(
                "select conname, confdeltype from pg_constraint where contype = 'f' and conname = any(:n)"
            ),
            {"n": list(FKS)},
        ).all()
    return {n: d for n, d in rows}


def _check(engine) -> str | None:
    with engine.connect() as conn:
        return conn.execute(
            sa.text(
                "select pg_get_constraintdef(oid) from pg_constraint where conname = 'ck_fetch_queue_requested_by'"
            )
        ).scalar()


def _index(engine) -> str | None:
    with engine.connect() as conn:
        return conn.execute(
            sa.text("select indexdef from pg_indexes where indexname = 'ix_napix_call_log_user_called'")
        ).scalar()


def test_0015_columns_fk_check_index(db_url, engine):
    wipe_if_migrated(db_url)
    assert _columns(engine) == {c: "YES" for c in COLUMNS}
    assert _fks(engine) == dict.fromkeys(FKS, "r")
    check = _check(engine)
    assert check is not None and "requested_by IS NULL" in check and "'request'" in check
    index = _index(engine)
    assert index is not None and "(user_id, called_at)" in index and "WHERE (user_id IS NOT NULL)" in index
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True, "compare_server_default": True})
        diff = compare_metadata(ctx, Base.metadata)
    real = [d for d in diff if not (d[0] == "modify_type" and isinstance(d[-1], sa.Enum))]
    assert real == [], real


def test_0015_downgrade_upgrade(db_url, engine):
    cfg = alembic_config(db_url)
    wipe_if_migrated(db_url)
    with sessionmaker(bind=engine)() as s:
        seed_all(s)
        s.commit()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "insert into fetch_queue (kind, ref, priority, lane) values ('dossier', 'GAHC010000000001', 30, "
                "'request'), ('dossier', 'GAHC010000000002', 44, 'load')"
            )
        )
        conn.execute(
            sa.text(
                "insert into napix_call_log (api, params_sha256, ok, rate_limit_remaining) "
                "values ('hc-cnr-api/CNR', 'x', true, 812)"
            )
        )
    command.downgrade(cfg, "0014")
    try:
        assert _columns(engine) == {}
        assert _fks(engine) == {} and _check(engine) is None and _index(engine) is None
        with engine.connect() as conn:
            assert conn.execute(sa.text("select count(*) from fetch_queue")).scalar() == 2
            assert conn.execute(sa.text("select count(*) from napix_call_log")).scalar() == 1
    finally:
        command.upgrade(cfg, "head")
    assert _columns(engine) == {c: "YES" for c in COLUMNS} and _check(engine) is not None
    with engine.connect() as conn:
        assert (
            conn.execute(sa.text("select count(*) from fetch_queue where requested_by is null")).scalar() == 2
        )
        assert (
            conn.execute(sa.text("select count(*) from napix_call_log where user_id is null")).scalar() == 1
        )
    wipe_if_migrated(db_url)
