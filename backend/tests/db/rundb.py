"""A test database per run (design github-and-ci, decisions 4 and 5).

`ASLMS_TEST_DATABASE_URL` names the server, the credentials and a base name (default `aslms_test`). Each pytest
session works in its own database, `<base>_<UTC yyyymmddHHMMSS>_<6 hex>`, created on the server at the start and
dropped at the end, so two sessions at once never touch each other's data. Cluster-wide state (the three roles and
`pg_monitor`) is serialised by an advisory lock held in the `postgres` maintenance database, which every run shares.

Three test-only variables (never application settings, never read from `.env`):
- `ASLMS_TEST_DB_PER_RUN` (default `1`): `0` uses the named database as before (wipe, downgrade, upgrade); the name
  must then contain `test`.
- `ASLMS_TEST_KEEP_DB` (default `0`): `1` keeps the run database at the end and prints its name.
- `ASLMS_TEST_REQUIRE_DB` (default `0`): `1` makes an unreachable server a failure instead of a skip (CI).

Standard library and SQLAlchemy only: the unit tests import the pure helpers without a database."""

from __future__ import annotations

import os
import re
import secrets
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.engine import URL, make_url

DEFAULT_URL = "postgresql+psycopg://aslms:aslms@127.0.0.1:5433/aslms_test"
MAX_NAME = 63  # PostgreSQL's identifier limit (NAMEDATALEN - 1)
SUFFIX_LEN = len("_20261020101500_a1b2c3")
STALE_AFTER = timedelta(hours=24)
LOCK_KEY = "aslms-test-cluster"
ROLES_SQL = """
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'aslms_owner') THEN CREATE ROLE aslms_owner NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'aslms_app') THEN CREATE ROLE aslms_app LOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'aslms_readonly') THEN CREATE ROLE aslms_readonly LOGIN; END IF;
END $$;
"""
ROLES = ("aslms_owner", "aslms_app", "aslms_readonly")


def flag(name: str, default: str) -> bool:
    return os.environ.get(name, default).strip() == "1"


def base_url() -> URL:
    return make_url(os.environ.get("ASLMS_TEST_DATABASE_URL", DEFAULT_URL))


def name_base(base: str) -> str:
    """The base name as used in run names: lowercase, cut so that the whole name stays within 63 characters."""
    return (base or "aslms_test").lower()[: MAX_NAME - SUFFIX_LEN]


def run_database_name(base: str, now: datetime | None = None, token: str | None = None) -> str:
    now = now or datetime.now(UTC)
    token = token or secrets.token_hex(3)
    return f"{name_base(base)}_{now.astimezone(UTC):%Y%m%d%H%M%S}_{token}"


def run_name_pattern(base: str) -> re.Pattern[str]:
    """Exactly `<base>_<14 digits>_<6 hex>`; nothing else is ever swept."""
    return re.compile(rf"^{re.escape(name_base(base))}_(\d{{14}})_[0-9a-f]{{6}}$")


def stale_names(names: list[str], base: str, now: datetime | None = None) -> list[str]:
    """The names that match the run pattern and whose timestamp is older than 24 hours."""
    now = now or datetime.now(UTC)
    pattern = run_name_pattern(base)
    out = []
    for name in names:
        m = pattern.match(name)
        if not m:
            continue
        try:
            stamp = datetime.strptime(m.group(1), "%Y%m%d%H%M%S").replace(tzinfo=UTC)
        except ValueError:
            continue
        if now - stamp > STALE_AFTER:
            out.append(name)
    return out


def check_named_database(name: str | None) -> None:
    """`ASLMS_TEST_DB_PER_RUN=0` wipes the named database: refused unless its name contains `test`."""
    if not name or "test" not in name.lower():
        raise ValueError(
            f"ASLMS_TEST_DB_PER_RUN=0 wipes the database named by ASLMS_TEST_DATABASE_URL; "
            f"{name!r} does not contain 'test', so it is refused"
        )


def url_string(url: URL) -> str:
    return url.render_as_string(hide_password=False)


def maintenance_url(url: URL) -> URL:
    return url.set(database="postgres")


def autocommit_engine(url: URL) -> sa.Engine:
    return sa.create_engine(url, poolclass=sa.pool.NullPool, isolation_level="AUTOCOMMIT")


_lock_state = threading.local()


@contextmanager
def cluster_lock(url: URL) -> Iterator[None]:
    """A session advisory lock in the `postgres` maintenance database (advisory locks are per database, so the lock
    lives where every run meets). Re-entrant inside one thread, so nested callers never wait on themselves."""
    depth = getattr(_lock_state, "depth", 0)
    if depth:
        _lock_state.depth = depth + 1
        try:
            yield
        finally:
            _lock_state.depth -= 1
        return
    eng = autocommit_engine(maintenance_url(url))
    try:
        with eng.connect() as conn:
            conn.execute(sa.text("SELECT pg_advisory_lock(hashtext(:k))"), {"k": LOCK_KEY})
            _lock_state.depth = 1
            try:
                yield
            finally:
                _lock_state.depth = 0
                conn.execute(sa.text("SELECT pg_advisory_unlock(hashtext(:k))"), {"k": LOCK_KEY})
    finally:
        eng.dispose()


def sweep_stale(conn: sa.Connection, base: str, now: datetime | None = None) -> list[str]:
    """Drop the stale run databases of earlier, killed runs. A plain DROP DATABASE (never FORCE) and only when no
    session is connected, so a live run is never touched. Returns the names dropped."""
    names = conn.execute(sa.text("SELECT datname FROM pg_database")).scalars().all()
    dropped = []
    for name in stale_names(list(names), base, now):
        busy = conn.execute(
            sa.text("SELECT count(*) FROM pg_stat_activity WHERE datname = :n"), {"n": name}
        ).scalar()
        if busy:
            continue
        try:
            conn.execute(sa.text(f'DROP DATABASE "{name}"'))
        except sa.exc.DBAPIError:  # someone connected in between, or another run dropped it first
            continue
        dropped.append(name)
    return dropped


def create_database(conn: sa.Connection, name: str) -> None:
    conn.execute(sa.text(f"CREATE DATABASE \"{name}\" TEMPLATE template0 ENCODING 'UTF8'"))


def drop_database(conn: sa.Connection, name: str) -> None:
    """The run's own database only, at the end of the session (FORCE ends connections a test leaked)."""
    conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def ensure_roles(conn: sa.Connection) -> None:
    """The three cluster roles, created if missing (0001's IF NOT EXISTS block is then a no-op)."""
    conn.execute(sa.text(ROLES_SQL))
