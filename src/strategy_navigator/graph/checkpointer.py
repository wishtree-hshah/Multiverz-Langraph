"""LangGraph Postgres checkpointer.

This is the durability layer: every node completion is persisted, so a run that
crashes mid-workflow (worker OOM, gateway wedge, deploy) resumes from the last
good node when the retry lane picks it up — it does not restart from zero.

``setup_checkpointer()`` (run once by ``strategy-navigator db upgrade``) creates
the ``checkpoints*`` tables. ``checkpointer_cm()`` yields a live saver bound to a
short-lived connection pool; open it per run in the worker.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool

from strategy_navigator.config import settings
from strategy_navigator.logging import get_logger

log = get_logger(__name__)

_CONNECTION_KWARGS = {"autocommit": True, "prepare_threshold": 0}


@contextlib.asynccontextmanager
async def checkpointer_cm() -> AsyncIterator[AsyncPostgresSaver]:
    async with AsyncConnectionPool(
        conninfo=settings.psycopg_url,
        min_size=1,
        max_size=settings.db_pool_min_size + 2,
        kwargs=_CONNECTION_KWARGS,
        open=False,
    ) as pool:
        await pool.open()
        yield AsyncPostgresSaver(pool)  # type: ignore[arg-type]


async def setup_checkpointer() -> None:
    async with checkpointer_cm() as saver:
        await saver.setup()
    log.info("checkpointer.schema_ready")
