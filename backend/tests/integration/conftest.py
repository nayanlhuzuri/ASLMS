"""Integration tests need a reachable Postgres. (SQLAlchemy 2 masks passwords in str(URL); always render with
hide_password=False.) They use a separate database (`<db>_test`) created on demand
and are skipped, not failed, when the server cannot be reached."""

from __future__ import annotations

import os

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url

from aslms.core.config import get_settings


def _test_url() -> str:
    override = os.environ.get("TEST_DATABASE_URL_SYNC")
    if override:
        return override
    url = make_url(get_settings().database_url_sync)
    return url.set(database=f"{url.database}_test").render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def test_db_url() -> str:
    url = make_url(_test_url())
    admin = sa.create_engine(
        url.set(database="postgres").render_as_string(hide_password=False), isolation_level="AUTOCOMMIT"
    )
    try:
        with admin.connect() as conn:
            exists = conn.execute(
                sa.text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": url.database}
            ).scalar()
            if not exists:
                conn.execute(sa.text(f'CREATE DATABASE "{url.database}"'))
    except sa.exc.OperationalError as e:  # server unreachable
        pytest.skip(f"Postgres not reachable: {e}")
    finally:
        admin.dispose()
    return url.render_as_string(hide_password=False)
