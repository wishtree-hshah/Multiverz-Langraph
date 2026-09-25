"""FastAPI application factory."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

from fastapi import FastAPI

from strategy_navigator.__about__ import __version__
from strategy_navigator.api.errors import install_exception_handlers
from strategy_navigator.api.middleware import RequestContextMiddleware
from strategy_navigator.api.routes import admin, health, runs, webhooks
from strategy_navigator.config import settings
from strategy_navigator.db.engine import dispose_engine
from strategy_navigator.logging import configure_logging, get_logger
from strategy_navigator.observability import instrument_fastapi, setup_tracing
from strategy_navigator.queue.app import app as queue_app

log = get_logger(__name__)


@contextlib.asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    setup_tracing()
    await queue_app.open_async()
    log.info("api.startup", version=__version__, env=settings.env)
    try:
        yield
    finally:
        await queue_app.close_async()
        await dispose_engine()
        log.info("api.shutdown")


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(
        title="Strategy Navigator",
        version=__version__,
        root_path=settings.api_root_path,
        lifespan=_lifespan,
    )
    app.add_middleware(RequestContextMiddleware)
    install_exception_handlers(app)

    app.include_router(health.router, tags=["health"])
    app.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
    app.include_router(runs.router, prefix="/runs", tags=["runs"])
    app.include_router(admin.router, prefix="/admin", tags=["admin"])

    instrument_fastapi(app)
    return app


app = create_app()
