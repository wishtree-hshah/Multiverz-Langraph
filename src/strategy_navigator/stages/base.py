"""Helpers shared by every stage node.

* :func:`stage_node` — decorator that wraps a node coroutine with a tracing span,
  structured start/end logs, and timing.
* :func:`get_request` / :func:`put_artifact` — typed access to graph state.
* :class:`StubStage` — raises :class:`StageNotImplementedError` so an un-ported
  workflow fails loudly into the dead-letter table instead of silently returning
  nothing.
"""

from __future__ import annotations

import functools
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from pydantic import BaseModel

from strategy_navigator.errors import StageNotImplementedError
from strategy_navigator.graph.state import PipelineState
from strategy_navigator.logging import get_logger
from strategy_navigator.observability import span

log = get_logger(__name__)

NodeFn = Callable[[PipelineState], Awaitable[dict[str, Any]]]
T = TypeVar("T", bound=BaseModel)


def stage_node(name: str) -> Callable[[NodeFn], NodeFn]:
    def decorator(fn: NodeFn) -> NodeFn:
        @functools.wraps(fn)
        async def wrapper(state: PipelineState) -> dict[str, Any]:
            started = time.monotonic()
            log.info("stage.start", stage=name)
            with span(f"stage.{name}"):
                try:
                    out = await fn(state)
                except Exception as exc:
                    log.error("stage.error", stage=name, error=str(exc), exc_info=True)
                    raise
            log.info("stage.end", stage=name, ms=round((time.monotonic() - started) * 1000))
            return out

        return wrapper

    return decorator


def get_request[T: BaseModel](state: PipelineState, schema: type[T]) -> T:
    return schema.model_validate(state["request"])


def artifact(state: PipelineState, key: str, default: Any = None) -> Any:
    return state.get("artifacts", {}).get(key, default)


def put_artifact(key: str, value: Any) -> dict[str, Any]:
    return {"artifacts": {key: value}}


def put_result(body: BaseModel | dict[str, Any]) -> dict[str, Any]:
    if isinstance(body, BaseModel):
        body = body.model_dump(by_alias=True, exclude_none=True)
    return {"result": body}


class StubStage:
    """Placeholder graph for a workflow that has not been ported yet."""

    def __init__(self, workflow: str) -> None:
        self.workflow = workflow

    def __call__(self) -> Any:
        from langgraph.graph import END, START, StateGraph

        wf = self.workflow

        async def _not_implemented(state: PipelineState) -> dict[str, Any]:
            raise StageNotImplementedError(
                f"Workflow {wf!r} is a stub — port its n8n nodes in "
                f"strategy_navigator/stages/{wf}.py before enabling it."
            )

        g: StateGraph = StateGraph(PipelineState)
        g.add_node("not_implemented", _not_implemented)
        g.add_edge(START, "not_implemented")
        g.add_edge("not_implemented", END)
        return g
