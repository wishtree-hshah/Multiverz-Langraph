"""Invoke / resume a single workflow graph.

Called by the queue task layer. Owns:
* building the compiled graph for a workflow (via the stage registry)
* binding the Postgres checkpointer (thread_id == run_id)
* the token tally for this run
* translating a LangGraph ``interrupt`` into a ``waiting_human`` outcome
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from langgraph.errors import GraphInterrupt
from langgraph.types import Command

from strategy_navigator.constants import Workflow
from strategy_navigator.graph.checkpointer import checkpointer_cm
from strategy_navigator.graph.state import initial_state
from strategy_navigator.llm import tokens
from strategy_navigator.logging import bind_context, get_logger
from strategy_navigator.observability import span

log = get_logger(__name__)


class OutcomeStatus(StrEnum):
    SUCCEEDED = "succeeded"
    WAITING_HUMAN = "waiting_human"


@dataclass(slots=True)
class RunOutcome:
    status: OutcomeStatus
    result: dict[str, Any] | None = None
    interrupt: Any = None
    token_usage: list[dict] = field(default_factory=list)


async def run_workflow_graph(
    *,
    workflow: Workflow,
    run_id: str,
    session_id: str,
    project_id: int | None,
    request: dict[str, Any],
    resume_value: Any = None,
) -> RunOutcome:
    from strategy_navigator.stages import get_graph_builder  # avoid import cycle

    builder = get_graph_builder(workflow)
    config = {
        "configurable": {"thread_id": run_id},
        "recursion_limit": 100,
    }

    tally = tokens.start_run_tally(run_id, session_id, str(workflow))

    with bind_context(run_id=run_id, session_id=session_id, workflow=str(workflow)):
        async with checkpointer_cm() as saver:
            graph = builder().compile(checkpointer=saver)
            payload: Any
            if resume_value is not None:
                payload = Command(resume=resume_value)
                log.info("graph.resume")
            else:
                payload = initial_state(
                    run_id=run_id,
                    session_id=session_id,
                    workflow=str(workflow),
                    project_id=project_id,
                    request=request,
                )
                log.info("graph.start")

            final_state: dict[str, Any] = {}
            with span(f"workflow.{workflow}", **{"sn.run_id": run_id}):
                try:
                    async for event in graph.astream(payload, config, stream_mode="values"):
                        final_state = event
                except GraphInterrupt as gi:
                    log.info("graph.interrupt")
                    return RunOutcome(
                        status=OutcomeStatus.WAITING_HUMAN,
                        interrupt=_interrupt_payload(gi),
                        token_usage=tally.as_callback_list(),
                    )

            # A resumed/streamed graph can still be sitting on an interrupt.
            snapshot = await graph.aget_state(config)
            if snapshot.next and _pending_interrupt(snapshot):
                log.info("graph.interrupt_pending")
                return RunOutcome(
                    status=OutcomeStatus.WAITING_HUMAN,
                    interrupt=_pending_interrupt(snapshot),
                    token_usage=tally.as_callback_list(),
                )

            log.info(
                "graph.done", cost_usd=round(sum(t.cost_usd for t in tally.by_model.values()), 4)
            )
            return RunOutcome(
                status=OutcomeStatus.SUCCEEDED,
                result=final_state.get("result"),
                token_usage=tally.as_callback_list(),
            )


def _interrupt_payload(gi: GraphInterrupt) -> Any:
    try:
        return gi.args[0][0].value  # type: ignore[index]
    except Exception:
        return {"raw": str(gi)}


def _pending_interrupt(snapshot: Any) -> Any:
    tasks = getattr(snapshot, "tasks", ()) or ()
    for t in tasks:
        for it in getattr(t, "interrupts", ()) or ():
            return getattr(it, "value", None)
    return None
