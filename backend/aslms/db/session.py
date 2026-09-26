"""Engine and sessions. One synchronous path for the API (FastAPI runs sync handlers in its thread pool),
Celery tasks, the CLI and Alembic, so every caller shares the same service code."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from aslms.core.config import get_settings


@lru_cache
def sync_engine() -> Engine:
    s = get_settings()
    # Behind PgBouncer in transaction mode, server-side prepared statements break (another client may get the
    # connection); psycopg's prepare_threshold=None turns them off.
    connect_args = {"prepare_threshold": None} if s.db_behind_pgbouncer else {}
    return create_engine(
        s.database_url_sync,
        pool_size=s.db_pool_size,
        max_overflow=s.db_max_overflow,
        pool_pre_ping=True,
        connect_args=connect_args,
    )


@lru_cache
def sync_session_factory() -> sessionmaker[Session]:
    return sessionmaker(sync_engine(), expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request, committed on success, rolled back on error."""
    with sync_session_factory()() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


@contextmanager
def sync_session() -> Iterator[Session]:
    """For Celery tasks, the CLI and background steps: commit on success, roll back on error."""
    with sync_session_factory()() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
