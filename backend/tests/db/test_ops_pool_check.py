"""`aslms ops pool-check` (design `followups-oct`, decision 5b): read-only, the holders really hold, the apart writes
are timed, and a starved apart pool is reported as a failure."""

from __future__ import annotations

import sqlalchemy as sa

from aslms.services import ops_pool_check


def _counts(engine) -> int:
    with engine.connect() as conn:
        return int(conn.execute(sa.text("SELECT count(*) FROM audit_log")).scalar())


def test_pool_check_passes_and_writes_nothing(migrated):
    main = sa.create_engine(migrated, pool_size=5, max_overflow=10, pool_timeout=30)
    apart = sa.create_engine(migrated, pool_size=2, max_overflow=0, pool_timeout=10)
    before = _counts(main)
    out = ops_pool_check.run(main, apart, holders=3, pages=5, apart_n=10, seconds=1.0)
    assert out["ok"] is True, out
    assert (out["holders"], out["holders_done"], out["apart"]) == (3, 3, 10)
    assert out["pages"] == 5 and out["timeouts"] == 0 and out["errors"] == {}
    assert out["apart_wait_max_ms"] < ops_pool_check.APART_LIMIT_MS
    assert _counts(main) == before
    main.dispose()
    apart.dispose()


def test_pool_check_fails_when_the_main_pool_is_exhausted(migrated):
    """Holders take every main connection and the pool timeout is short: the page transactions time out."""
    main = sa.create_engine(migrated, pool_size=2, max_overflow=0, pool_timeout=1)
    apart = sa.create_engine(migrated, pool_size=1, max_overflow=0, pool_timeout=1)
    out = ops_pool_check.run(main, apart, holders=2, pages=3, apart_n=2, seconds=2.0)
    assert out["ok"] is False and out["timeouts"] >= 1
    assert out["apart"] == 2, "the apart writes have their own engine and still pass"
    main.dispose()
    apart.dispose()
