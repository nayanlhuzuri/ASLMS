"""Definition of done for schema changes: upgrade head → downgrade base → upgrade head works, and the
resulting tables are exactly the ones the models declare."""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config

from alembic import command
from aslms.domain import Base

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def _tables(url: str) -> set[str]:
    engine = sa.create_engine(url)
    try:
        return set(sa.inspect(engine).get_table_names()) - {"alembic_version"}
    finally:
        engine.dispose()


def test_migrations_round_trip(test_db_url: str, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL_SYNC", test_db_url)
    from aslms.core.config import get_settings

    get_settings.cache_clear()
    cfg = _alembic_config(test_db_url)

    command.downgrade(cfg, "base")
    assert _tables(test_db_url) == set()

    command.upgrade(cfg, "head")
    assert _tables(test_db_url) == set(Base.metadata.tables)

    command.downgrade(cfg, "base")
    assert _tables(test_db_url) == set()

    command.upgrade(cfg, "head")
    assert _tables(test_db_url) == set(Base.metadata.tables)
    get_settings.cache_clear()
    # the schema was dropped and recreated: pooled connections hold prepared statements for the old tables
    from aslms.db.session import sync_engine

    sync_engine().dispose()


def test_seed_is_idempotent(test_db_url: str) -> None:
    from sqlalchemy.orm import Session

    from aslms.db.seed import run_seed
    from aslms.domain.org import Office, User
    from aslms.domain.reference import Court

    engine = sa.create_engine(test_db_url)
    try:
        with Session(engine) as s:
            run_seed(s)
            s.commit()
            run_seed(s)
            s.commit()
            assert s.scalar(sa.select(sa.func.count()).select_from(Office)) == 3
            assert s.scalar(sa.select(sa.func.count()).select_from(Court)) == 1
            assert s.scalar(sa.select(sa.func.count()).select_from(User)) == 1
    finally:
        engine.dispose()
