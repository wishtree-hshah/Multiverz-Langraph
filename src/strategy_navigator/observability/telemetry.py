"""OpenTelemetry tracing — entirely optional.

When ``SN_OTEL_EXPORTER_OTLP_ENDPOINT`` is unset every function here is a no-op,
so importing/using :func:`span` costs nothing in tests or local dev.

Spans we emit by hand:
* ``workflow.<name>``       — one per queued run (in queue/tasks.py)
* ``stage.<node>``          — one per graph node (in stages/base.py)
* ``llm.chat``              — one per model call (in llm/client.py)
* ``tool.jina.<op>``        — one per search/reader call (in tools/search.py)
* ``callback.<workflow>``   — one per backend callback (in callbacks/client.py)
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import Any

from strategy_navigator.config import settings
from strategy_navigator.logging import get_logger

log = get_logger(__name__)

_TRACER: Any = None


def setup_tracing() -> None:
    global _TRACER
    if _TRACER is not None or not settings.tracing_enabled:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(
            resource=Resource.create(
                {"service.name": settings.service_name, "deployment.environment": settings.env}
            )
        )
        provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(endpoint=f"{settings.otel_exporter_otlp_endpoint}/v1/traces")
            )
        )
        trace.set_tracer_provider(provider)
        _TRACER = trace.get_tracer(settings.service_name)
        log.info("tracing.enabled", endpoint=settings.otel_exporter_otlp_endpoint)
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("tracing.setup_failed", error=str(exc))


def instrument_fastapi(app: Any) -> None:
    if not settings.tracing_enabled:
        return
    with contextlib.suppress(Exception):  # pragma: no cover
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        FastAPIInstrumentor.instrument_app(app)
        HTTPXClientInstrumentor().instrument()


@contextlib.contextmanager
def span(name: str, **attributes: Any) -> Iterator[None]:
    if _TRACER is None:
        yield
        return
    with _TRACER.start_as_current_span(name) as s:  # pragma: no cover - needs collector
        for k, v in attributes.items():
            if v is not None:
                s.set_attribute(k, v)
        yield
