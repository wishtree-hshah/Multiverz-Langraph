"""Structured logging.

* One configuration call — :func:`configure_logging` — at process start (API,
  worker, CLI all call it).
* ``structlog`` renders JSON in staging/prod, colored console locally.
* A :class:`contextvars.ContextVar` carries correlation ids (``session_id``,
  ``run_id``, ``workflow``, ``request_id``) so every log line inside a run is
  automatically tagged without threading a logger through every function.

Usage::

    from strategy_navigator.logging import get_logger, bind_context

    log = get_logger(__name__)
    with bind_context(session_id=sid, workflow="domain_agent"):
        log.info("stage.start", agent_count=3)
"""

from __future__ import annotations

import contextlib
import logging
import sys
from collections.abc import Iterator
from typing import Any

import structlog
from structlog.contextvars import bind_contextvars, reset_contextvars

from strategy_navigator.config import settings

_CONFIGURED = False


def configure_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    shared: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        timestamper,
    ]

    if settings.log_json:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    structlog.configure(
        processors=[*shared, structlog.processors.format_exc_info, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )

    # Route stdlib logging (uvicorn, sqlalchemy, litellm, procrastinate) through structlog.
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processor=renderer,
            foreign_pre_chain=shared,
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    for noisy, lvl in {
        "httpx": logging.WARNING,
        "httpcore": logging.WARNING,
        "LiteLLM": logging.WARNING,
        "litellm": logging.WARNING,
        "sqlalchemy.engine": logging.WARNING,
        "procrastinate": logging.INFO,
        "uvicorn.access": logging.WARNING,
    }.items():
        logging.getLogger(noisy).setLevel(lvl)

    _CONFIGURED = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]


@contextlib.contextmanager
def bind_context(**kwargs: Any) -> Iterator[None]:
    """Bind correlation ids for the duration of the block (and any nested tasks)."""
    tokens = bind_contextvars(**{k: v for k, v in kwargs.items() if v is not None})
    try:
        yield
    finally:
        reset_contextvars(**tokens)
