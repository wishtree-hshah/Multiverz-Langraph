"""Request-scoped logging context + access log + timing."""

from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from strategy_navigator.logging import bind_context, get_logger

log = get_logger("api.access")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        started = time.monotonic()
        with bind_context(request_id=request_id):
            try:
                response = await call_next(request)
            except Exception:
                log.error(
                    "http.error",
                    method=request.method,
                    path=request.url.path,
                    ms=round((time.monotonic() - started) * 1000),
                    exc_info=True,
                )
                raise
            elapsed = round((time.monotonic() - started) * 1000)
            log.info(
                "http.request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                ms=elapsed,
            )
            response.headers["x-request-id"] = request_id
            return response
