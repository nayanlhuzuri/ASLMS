"""The connection budget (design `followups-oct`, decision 4): NAPIX_REQUEST_SLOTS + 1 worker + 1 scheduler +
DB_APART_POOL_SIZE + a reserve of 4 must not exceed PGBOUNCER_DEFAULT_POOL_SIZE; preflight reports a budget over it
as an error in prod and a warning in dev, naming the variables and never their values. The main pool is set
explicitly (5 + 10, 30 s)."""

from __future__ import annotations

from aslms.core.config import Settings
from aslms.db import session as db_session
from aslms.services import preflight
from tests.unit.test_preflight import good


def test_defaults_satisfy_the_formula():
    s = Settings(_env_file=None)
    assert (s.napix_request_slots, s.db_apart_pool_size, s.pgbouncer_default_pool_size) == (6, 3, 20)
    assert (s.db_apart_pool_timeout_seconds, s.napix_request_wait_seconds) == (10, 20)
    assert preflight.budget_total(s) == 15 <= s.pgbouncer_default_pool_size
    assert preflight.connection_budget(s) is None
    assert preflight.check(good()) == [], "the good prod settings pass with the default budget"


def test_budget_over_the_pgbouncer_pool_is_an_error_in_prod():
    findings = preflight.check(good(napix_request_slots=12))  # 12 + 1 + 1 + 3 + 4 = 21 > 20
    (f,) = [f for f in findings if f.variable == "connection_budget"]
    assert f.level == preflight.ERROR
    assert "NAPIX_REQUEST_SLOTS" in f.message and "PGBOUNCER_DEFAULT_POOL_SIZE" in f.message
    assert "12" not in f.message and "21" not in f.message, "names the variables, never their values"


def test_budget_over_the_pgbouncer_pool_is_a_warning_in_dev():
    s = Settings(_env_file=None, app_env="dev", db_apart_pool_size=5, pgbouncer_default_pool_size=16)
    f = preflight.connection_budget(s)
    assert f is not None and f.level == preflight.WARNING
    preflight.raise_on_errors([f], is_prod=False)  # a warning never stops the start


def test_raising_pgbouncer_pool_clears_the_finding():
    assert preflight.connection_budget(good(napix_request_slots=12, pgbouncer_default_pool_size=25)) is None


def test_main_pool_is_explicit():
    engine = db_session.get_engine("postgresql+psycopg://u:p@127.0.0.1:1/never_connected")
    assert (engine.pool.size(), engine.pool._max_overflow, engine.pool._timeout) == (5, 10, 30)


def test_apart_pool_has_no_overflow():
    engine = db_session.get_apart_engine("postgresql+psycopg://u:p@127.0.0.1:1/never_connected", 3, 10)
    assert (engine.pool.size(), engine.pool._max_overflow, engine.pool._timeout) == (3, 0, 10)
