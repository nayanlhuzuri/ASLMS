"""Engine and session factory (synchronous SQLAlchemy 2 over psycopg 3)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from aslms.core.config import get_settings


@lru_cache(maxsize=4)
def get_engine(url: str | None = None) -> Engine:
    return create_engine(url or get_settings().database_url_sync, pool_pre_ping=True, future=True)


def get_sessionmaker(url: str | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(url), expire_on_commit=False, autoflush=False)


@contextmanager
def session_scope(url: str | None = None) -> Iterator[Session]:
    """One transaction: commit on success, roll back on any exception."""
    session = get_sessionmaker(url)()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()
