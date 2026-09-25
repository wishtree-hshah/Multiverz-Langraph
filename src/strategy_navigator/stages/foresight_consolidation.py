"""foresight_consolidation workflow.

n8n source: "Foresight Consolidation Agent.json" (25 nodes), node "Foresight
Consolidation Agent" — prompt is Mongo promptId "8", pulled to
prompts/_mongo/8.md.

Graph:
    START -> flatten_initiatives -> consolidate -> assemble_callback -> END

`flatten_initiatives` reproduces the n8n pre-processing node the prompt's own
docstring describes: it flattens every selected agent's 10-step output down to
its high-impact initiatives (``solutionValues.solutionOpportunities``), each
tagged with the contributing agent's ``source_agent`` key.
"""

from __future__ import annotations

import json
from typing import Any

from langgraph.graph import END, START, StateGraph

from strategy_navigator.graph.state import PipelineState
from strategy_navigator.llm.structured import generate_structured
from strategy_navigator.prompts import bindings, render_prompt
from strategy_navigator.schemas.common import Idea
from strategy_navigator.schemas.foresight import (
    ForesightConsolidationCallback,
    ForesightConsolidationOutput,
    ForesightConsolidationRequest,
)
from strategy_navigator.stages.base import get_request, put_artifact, put_result, stage_node


@stage_node("flatten_initiatives")
async def flatten_initiatives(state: PipelineState) -> dict[str, Any]:
    req = get_request(state, ForesightConsolidationRequest)
    initiatives = [
        {**opp, "source_agent": solution.source_agent}
        for solution in req.solutions
        for opp in solution.opportunities
    ]
    return put_artifact("initiatives", initiatives)


@stage_node("consolidate")
async def consolidate(state: PipelineState) -> dict[str, Any]:
    req = get_request(state, ForesightConsolidationRequest)
    initiatives = state["artifacts"]["initiatives"]
    prompt_vars = bindings.build(
        req.project, all_initiatives=json.dumps(initiatives, ensure_ascii=False)
    )
    system = render_prompt("foresight_consolidation.system", **prompt_vars)
    output = await generate_structured(
        ForesightConsolidationOutput,
        [{"role": "system", "content": system}],
        stage="consolidate",
        temperature=0.2,
    )
    return put_artifact("consolidated", output.model_dump())


@stage_node("assemble_callback")
async def assemble_callback(state: PipelineState) -> dict[str, Any]:
    req = get_request(state, ForesightConsolidationRequest)
    output = ForesightConsolidationOutput.model_validate(state["artifacts"]["consolidated"])
    callback = ForesightConsolidationCallback(
        session_id=req.session_id,
        ideas=[Idea.model_validate(i.model_dump()) for i in output.ideas],
        execution_id=state["run_id"],
    )
    return put_result(callback)


def build() -> StateGraph:
    g: StateGraph = StateGraph(PipelineState)
    g.add_node("flatten_initiatives", flatten_initiatives)
    g.add_node("consolidate", consolidate)
    g.add_node("assemble_callback", assemble_callback)
    g.add_edge(START, "flatten_initiatives")
    g.add_edge("flatten_initiatives", "consolidate")
    g.add_edge("consolidate", "assemble_callback")
    g.add_edge("assemble_callback", END)
    return g
