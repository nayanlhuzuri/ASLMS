"""Engine and session factory (synchronous SQLAlchemy 2 over psycopg 3).

Two engines per process (design `followups-oct`, decisions 2 and 4):
- the main engine, one `QueuePool` of `MAIN_POOL_SIZE` + `MAIN_MAX_OVERFLOW` connections with a `MAIN_POOL_TIMEOUT`
  wait, set here explicitly rather than left to the library's defaults;
- the apart engine (`DB_APART_POOL_SIZE`, no overflow, `DB_APART_POOL_TIMEOUT_SECONDS`), only for the api's apart
  writes: the NAPIX call rows and the apart audit rows of the request paths. An apart session opens, writes one to
  three rows, commits and closes in milliseconds, so a writer never waits behind a request that holds a connection
  across a NAPIX wait."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from aslms.core.config import get_settings

MAIN_POOL_SIZE = 5
MAIN_MAX_OVERFLOW = 10
MAIN_POOL_TIMEOUT = 30


@lru_cache(maxsize=4)
def get_engine(url: str | None = None) -> Engine:
    return create_engine(
        url or get_settings().database_url_sync,
        pool_size=MAIN_POOL_SIZE,
        max_overflow=MAIN_MAX_OVERFLOW,
        pool_timeout=MAIN_POOL_TIMEOUT,
        pool_pre_ping=True,
        future=True,
    )


def get_sessionmaker(url: str | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(url), expire_on_commit=False, autoflush=False)


@lru_cache(maxsize=4)
def get_apart_engine(
    url: str | None = None, pool_size: int | None = None, pool_timeout: int | None = None
) -> Engine:
    settings = get_settings()
    return create_engine(
        url or settings.database_url_sync,
        pool_size=pool_size or settings.db_apart_pool_size,
        max_overflow=0,
        pool_timeout=pool_timeout or settings.db_apart_pool_timeout_seconds,
        pool_pre_ping=True,
        future=True,
    )


def get_apart_sessionmaker(
    url: str | None = None, pool_size: int | None = None, pool_timeout: int | None = None
) -> sessionmaker[Session]:
    return sessionmaker(
        bind=get_apart_engine(url, pool_size, pool_timeout), expire_on_commit=False, autoflush=False
    )


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
