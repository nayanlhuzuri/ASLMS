"""Engines and sessions: async for the API, sync for Alembic, Celery tasks and the CLI."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from aslms.core.config import get_settings


@lru_cache
def async_engine() -> AsyncEngine:
    s = get_settings()
    return create_async_engine(
        s.database_url, pool_size=s.db_pool_size, max_overflow=s.db_max_overflow, pool_pre_ping=True
    )


@lru_cache
def sync_engine():
    s = get_settings()
    return create_engine(
        s.database_url_sync, pool_size=s.db_pool_size, max_overflow=s.db_max_overflow, pool_pre_ping=True
    )


@lru_cache
def async_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(async_engine(), expire_on_commit=False)


@lru_cache
def sync_session_factory() -> sessionmaker[Session]:
    return sessionmaker(sync_engine(), expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request, committed on success, rolled back on error."""
    async with async_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@contextmanager
def sync_session() -> Iterator[Session]:
    """For Celery tasks and CLI commands."""
    with sync_session_factory()() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
