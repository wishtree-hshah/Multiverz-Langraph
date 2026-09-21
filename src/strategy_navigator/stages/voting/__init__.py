"""voting workflow  (reference implementation of fan-out).

n8n source: "Voting Agent (Parent).json" + "Voting Agent (Child).json" +
"Voting Middleware.json".

Graph:
    START -> plan -> (Send: score_batch × N) -> aggregate -> END

`plan` explodes (agents × idea-batches) into LangGraph ``Send`` messages — the
direct equivalent of the n8n parent's ``splitInBatches`` + ``executeWorkflow``
fan-out, but with real concurrency and per-child checkpointing.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from strategy_navigator.graph.state import PipelineState
from strategy_navigator.schemas.voting import VotingRequest
from strategy_navigator.stages.base import get_request, stage_node
from strategy_navigator.stages.voting.aggregate import aggregate
from strategy_navigator.stages.voting.child import score_batch


@stage_node("plan")
async def plan(state: PipelineState) -> dict:
    # No state mutation; routing happens in `fan_out`.
    return {}


def fan_out(state: PipelineState) -> list[Send]:
    req = get_request(state, VotingRequest)
    size = max(1, req.child_batch_size)
    batches = [req.ideas[i : i + size] for i in range(0, len(req.ideas), size)]
    sends: list[Send] = []
    for agent in req.agents:
        for bi, batch in enumerate(batches):
            sends.append(
                Send(
                    "score_batch",
                    {
                        "run_id": state["run_id"],
                        "session_id": state["session_id"],
                        "workflow": state["workflow"],
                        "request": state["request"],
                        "_child": {
                            "agent": agent.model_dump(),
                            "batch_index": bi,
                            "ideas": [i.model_dump() for i in batch],
                        },
                    },
                )
            )
    return sends


def build() -> StateGraph:
    g: StateGraph = StateGraph(PipelineState)
    g.add_node("plan", plan)
    g.add_node("score_batch", score_batch)
    g.add_node("aggregate", aggregate)
    g.add_edge(START, "plan")
    g.add_conditional_edges("plan", fan_out, ["score_batch"])
    g.add_edge("score_batch", "aggregate")
    g.add_edge("aggregate", END)
    return g
