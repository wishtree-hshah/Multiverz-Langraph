"""Map domain exceptions to HTTP responses."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from strategy_navigator.errors import (
    InvalidPayloadError,
    PermanentError,
    StrategyNavigatorError,
    TransientError,
    UnknownWorkflowError,
)
from strategy_navigator.logging import get_logger

log = get_logger("api.errors")


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(InvalidPayloadError)
    @app.exception_handler(UnknownWorkflowError)
    async def _bad_request(_: Request, exc: PermanentError) -> JSONResponse:
        return JSONResponse(
            status_code=400, content={"error": type(exc).__name__, "detail": str(exc)}
        )

    @app.exception_handler(TransientError)
    async def _service_unavailable(_: Request, exc: TransientError) -> JSONResponse:
        log.warning("api.transient", error=str(exc))
        return JSONResponse(
            status_code=503, content={"error": type(exc).__name__, "detail": str(exc)}
        )

    @app.exception_handler(StrategyNavigatorError)
    async def _generic(_: Request, exc: StrategyNavigatorError) -> JSONResponse:
        log.error("api.error", error=str(exc), exc_info=True)
        return JSONResponse(
            status_code=500, content={"error": type(exc).__name__, "detail": str(exc)}
        )
