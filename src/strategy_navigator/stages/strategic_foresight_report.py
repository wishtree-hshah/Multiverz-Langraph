"""strategic_foresight_report workflow.

No n8n workflow export exists under this name in either ``challenges-n8n/`` or
``strategy-navigator-n8n/`` (checked both). The operative prompt is real,
though: Mongo ``prompt_list`` id ``6`` ("Report Generation"), recovered
byte-exact from ``strategy-navigator-n8n/Admin Workflows/Prompt seed.json``'s
pinned webhook test payload — see ``prompts/_mongo/6.md``. That prompt's own
"5.1 n8n output parser schema" section is the ground truth for
:class:`schemas.foresight_report.StrategicForesightReportOutput`.

Graph:
    START -> prepare_inputs -> generate_report -> assemble_callback -> END

One structured LLM call. ``prepare_inputs`` computes the participant-metrics
counters the prompt's section 2.1.2 requires (n8n's would-be Set node — these
aren't in the trigger DTO as flat counts, only as nested
``ideationProcess``/``metrics`` blocks) and JSON-stringifies the two
"authoritative datasets" per the prompt's own instruction.
"""

from __future__ import annotations

import json
from typing import Any

from langgraph.graph import END, START, StateGraph

from strategy_navigator.graph.state import PipelineState
from strategy_navigator.llm.structured import generate_structured
from strategy_navigator.prompts import bindings, render_prompt
from strategy_navigator.schemas.foresight_report import (
    StrategicForesightReportCallback,
    StrategicForesightReportOutput,
    StrategicForesightReportRequest,
)
from strategy_navigator.stages.base import get_request, put_artifact, put_result, stage_node


def _count(block: dict[str, Any], key: str) -> int:
    v = block.get(key)
    if isinstance(v, dict):
        return int(v.get("count", 0) or 0)
    return int(v or 0)


@stage_node("prepare_inputs")
async def prepare_inputs(state: PipelineState) -> dict[str, Any]:
    req = get_request(state, StrategicForesightReportRequest)
    ip = req.ideation_process
    metrics = req.metrics

    foundational = _count(ip, "foundationalAgents") or int(
        metrics.get("foundationalAgentsCount", 0) or 0
    )
    contextual = _count(ip, "contextualAgents") or int(metrics.get("contextualAgentsCount", 0) or 0)
    human_ideators = _count(ip, "humanIdeators") or int(metrics.get("humanIdeatorsCount", 0) or 0)
    agent_count = foundational + contextual
    solution_ideas_count = int(metrics.get("solutionIdeasCount", 0) or 0) or sum(
        len(s.get("solutionIdeas", []) or []) for s in req.solutions
    )

    counters = {
        "participant_total_count": agent_count + human_ideators,
        "human_count": human_ideators,
        "agent_count": agent_count,
        "project_ideas_count": len(req.project_ideas),
        "solution_ideas_count": solution_ideas_count,
        "foundational_agent_count": foundational,
        "contextual_agent_count": contextual,
        "human_ideators_count": human_ideators,
    }
    return put_artifact("counters", counters)


@stage_node("generate_report")
async def generate_report(state: PipelineState) -> dict[str, Any]:
    req = get_request(state, StrategicForesightReportRequest)
    counters = state["artifacts"]["counters"]

    prompt_vars = bindings.build(
        req.project,
        sessionId=req.session_id,
        target_audience=req.target_audience,
        context_and_expectations=req.context_and_expectations,
        project_ideas_dataset=json.dumps(req.project_ideas, ensure_ascii=False),
        solutions_dataset=json.dumps(req.solutions, ensure_ascii=False),
        **counters,
    )
    system = render_prompt("strategic_foresight_report.system", **prompt_vars)
    output = await generate_structured(
        StrategicForesightReportOutput,
        [
            {"role": "system", "content": system},
            {"role": "user", "content": "Generate the report."},
        ],
        stage="generate_report",
        temperature=0.4,
    )
    return put_artifact("report", output.model_dump())


@stage_node("assemble_callback")
async def assemble_callback(state: PipelineState) -> dict[str, Any]:
    req = get_request(state, StrategicForesightReportRequest)
    output = StrategicForesightReportOutput.model_validate(state["artifacts"]["report"])
    callback = StrategicForesightReportCallback(
        session_id=req.session_id,
        project_id=req.project_id,
        output=output.model_dump(by_alias=True),
        execution_id=state["run_id"],
    )
    return put_result(callback)


def build() -> StateGraph:
    g: StateGraph = StateGraph(PipelineState)
    g.add_node("prepare_inputs", prepare_inputs)
    g.add_node("generate_report", generate_report)
    g.add_node("assemble_callback", assemble_callback)
    g.add_edge(START, "prepare_inputs")
    g.add_edge("prepare_inputs", "generate_report")
    g.add_edge("generate_report", "assemble_callback")
    g.add_edge("assemble_callback", END)
    return g
