"""Database tests run against a real PostgreSQL (the Compose `postgres` service, database `aslms_test`).
They are skipped when it is not reachable. The schema is built by the real migration, never by create_all."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session, sessionmaker

BACKEND = Path(__file__).resolve().parents[2]
TEST_URL = os.environ.get(
    "ASLMS_TEST_DATABASE_URL", "postgresql+psycopg://aslms:aslms@localhost:5433/aslms_test"
)


def alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@pytest.fixture(scope="session")
def db_url() -> str:
    try:
        engine = sa.create_engine(TEST_URL, poolclass=sa.pool.NullPool)
        with engine.connect() as conn:
            conn.execute(sa.text("select 1"))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(
            f"test database not reachable ({exc.__class__.__name__}); start `docker compose up -d postgres`"
        )
    return TEST_URL


@pytest.fixture(scope="session")
def migrated(db_url: str) -> Iterator[str]:
    """Head of the migration chain on a clean test database."""
    cfg = alembic_config(db_url)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield db_url


@pytest.fixture(scope="session")
def engine(migrated: str) -> Iterator[sa.Engine]:
    eng = sa.create_engine(migrated, poolclass=sa.pool.NullPool)
    yield eng
    eng.dispose()


@pytest.fixture()
def session(engine: sa.Engine) -> Iterator[Session]:
    """A session whose work is rolled back at the end of the test."""
    conn = engine.connect()
    trans = conn.begin()
    sess = sessionmaker(bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint")()
    try:
        yield sess
    finally:
        sess.close()
        trans.rollback()
        conn.close()
