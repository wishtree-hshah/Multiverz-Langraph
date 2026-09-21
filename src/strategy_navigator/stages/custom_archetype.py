"""custom_archetype workflow.

n8n source: "Custom archetype.json" (10 nodes), node "AI Agent" — full prompt
text inline, checked in verbatim at prompts/custom_archetype.md.

Graph:
    START -> generate_archetype -> assemble_callback -> END

One structured LLM call normalises the user's partial archetype spec into a
complete, confirmed definition with per-field provenance.
"""

from __future__ import annotations

import json
from typing import Any

from langgraph.graph import END, START, StateGraph

from strategy_navigator.graph.state import PipelineState
from strategy_navigator.llm.structured import generate_structured
from strategy_navigator.prompts import render, render_prompt
from strategy_navigator.schemas.capstone import (
    CustomArchetypeCallback,
    CustomArchetypeOutput,
    CustomArchetypeRequest,
)
from strategy_navigator.stages.base import get_request, put_artifact, put_result, stage_node


@stage_node("generate_archetype")
async def generate_archetype(state: PipelineState) -> dict[str, Any]:
    req = get_request(state, CustomArchetypeRequest)
    system = render_prompt("custom_archetype.system")
    payload_json = json.dumps(req.spec.model_dump(by_alias=True, exclude_none=True))
    user = render("custom_archetype.user", payload_json=payload_json)
    output = await generate_structured(
        CustomArchetypeOutput,
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        stage="generate_archetype",
        temperature=0.2,
    )
    return put_artifact("archetype_output", output.model_dump())


@stage_node("assemble_callback")
async def assemble_callback(state: PipelineState) -> dict[str, Any]:
    req = get_request(state, CustomArchetypeRequest)
    output = CustomArchetypeOutput.model_validate(state["artifacts"]["archetype_output"])
    callback = CustomArchetypeCallback(
        session_id=req.session_id,
        status="assembled",
        archetype=output.archetype,
        provenance=output.provenance,
        execution_id=state["run_id"],
    )
    return put_result(callback)


def build() -> StateGraph:
    g: StateGraph = StateGraph(PipelineState)
    g.add_node("generate_archetype", generate_archetype)
    g.add_node("assemble_callback", assemble_callback)
    g.add_edge(START, "generate_archetype")
    g.add_edge("generate_archetype", "assemble_callback")
    g.add_edge("assemble_callback", END)
    return g
