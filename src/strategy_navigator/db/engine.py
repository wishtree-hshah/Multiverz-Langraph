"""Async SQLAlchemy engine + session helpers for app-owned tables.

LangGraph checkpoints and procrastinate jobs live in the same database but are
managed by their own libraries — this engine only touches the tables declared in
:mod:`strategy_navigator.db.models`.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from strategy_navigator.config import settings


@lru_cache
def get_engine() -> AsyncEngine:
    return create_async_engine(
        settings.sqlalchemy_url,
        pool_size=settings.db_pool_max_size,
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args={"options": f"-c statement_timeout={settings.db_statement_timeout_ms}"},
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False, autoflush=False)


@contextlib.asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Transactional session; commits on success, rolls back on error."""
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
