"""strategy_form_idea_generation workflow  (fan-out, one Send per template).

No n8n workflow export exists under this name in either ``challenges-n8n/`` or
``strategy-navigator-n8n/`` (checked both). The operative prompt is real,
though: Mongo ``prompt_list`` id ``4`` ("Idea Extract with Solution"),
recovered byte-exact from ``strategy-navigator-n8n/Admin Workflows/Prompt
seed.json``'s pinned webhook test payload — see ``prompts/_mongo/4.md``.

Trigger shape is genuinely different from every other workflow in this repo:
``CustomizeTemplateService.processIdea`` (challenges-backend) POSTs a bare
**array** of ``{runId, solution: {projectId, templateId, templateSolution,
...}, usermetadata}`` — one item per customized template the user submitted,
all sharing one ``runId``. ``payload_adapter._adapt_strategy_form_idea_generation``
flattens that into one run with a ``templates`` list; this graph fans out one
``Send`` per template (the direct equivalent of n8n's per-template
``executeWorkflow`` sub-call, had this workflow been exported) and reuses
``PipelineState["partials"]`` (see ``stages/voting``) to collect results.

Graph:
    START -> plan -> (Send: score_template x N) -> aggregate -> END

Callback shape: ``receiveSolutionExtractedIdeasFromN8nBody`` (customize-
template.service.ts) expects each array item to echo back
``{runId, user, project, templateId, results: [{title,summary,categories,
sources}]}`` — reuses ``schemas.ideas.ExtractedIdea``/``IdeaExtractionOutput``
verbatim since prompt 4's output format is character-for-character the same
array shape as prompt 2's (idea_extraction).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from strategy_navigator.graph.state import PipelineState
from strategy_navigator.llm.structured import generate_structured
from strategy_navigator.logging import get_logger
from strategy_navigator.prompts import render_prompt
from strategy_navigator.schemas.ideas import (
    FormIdeaGenerationCallback,
    FormIdeaGenerationRequest,
    FormIdeaGenerationRow,
    FormIdeaTemplateInput,
    IdeaExtractionOutput,
)
from strategy_navigator.stages.base import get_request, put_result, stage_node
from strategy_navigator.tools.search import jina_search

log = get_logger(__name__)


@stage_node("plan")
async def plan(state: PipelineState) -> dict:
    # No state mutation; routing happens in `fan_out`.
    return {}


def fan_out(state: PipelineState) -> list[Send]:
    req = get_request(state, FormIdeaGenerationRequest)
    sends: list[Send] = []
    for template in req.templates:
        sends.append(
            Send(
                "score_template",
                {
                    "run_id": state["run_id"],
                    "session_id": state["session_id"],
                    "workflow": state["workflow"],
                    "request": state["request"],
                    "_child": {
                        "template": template.model_dump(),
                        "usermetadata": req.usermetadata,
                    },
                },
            )
        )
    return sends


async def _research(project_name: str) -> list[dict[str, str]]:
    queries = [f"{project_name} strategy trends 2026", f"{project_name} innovation case study"]
    results = await asyncio.gather(
        *(jina_search(q, top_k=3) for q in queries), return_exceptions=True
    )
    hits: list[dict[str, str]] = []
    for r in results:
        if isinstance(r, BaseException):
            log.warning("strategy_form_idea_generation.search_failed", error=str(r))
            continue
        hits.extend({"title": h.title, "url": h.url, "snippet": h.snippet} for h in r)
    return hits[:6]


@stage_node("score_template")
async def score_template(state: PipelineState) -> dict[str, Any]:
    child = state["_child"]
    template = FormIdeaTemplateInput.model_validate(child["template"])
    usermetadata = child["usermetadata"]

    hits = await _research(template.project_name)
    research_block = (
        "\n".join(f"- {h['title']}: {h['url']} — {h['snippet']}" for h in hits) or "(no results)"
    )

    system = render_prompt(
        "strategy_form_idea_generation.system",
        json_solution=json.dumps(template.template_solution, ensure_ascii=False),
        previous_agent_ideas="[]",
    )
    user = (
        "Supplementary research (from live search, use to ground scoring — "
        "do not fabricate beyond these plus the input):\n" + research_block
    )
    output = await generate_structured(
        IdeaExtractionOutput,
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        stage="score_template",
        temperature=0.5,
    )

    req = get_request(state, FormIdeaGenerationRequest)
    row = FormIdeaGenerationRow(
        # NOT state["run_id"] (our internal "workflow:sessionId" composite) —
        # the backend's n8n_idea_logs row is keyed by the raw runId UUID it
        # generated and sent us, which payload_adapter carried through as
        # sessionId (see _adapt_strategy_form_idea_generation).
        run_id=req.session_id,
        user=usermetadata,
        project={"id": template.project_id},
        template_id=template.template_id,
        results=output.ideas,
    )
    log.info(
        "strategy_form_idea_generation.template_done",
        template_id=template.template_id,
        ideas=len(output.ideas),
    )
    return {"partials": [row.model_dump(by_alias=True)]}


@stage_node("aggregate")
async def aggregate(state: PipelineState) -> dict[str, Any]:
    rows: list[dict[str, Any]] = state.get("partials", [])
    callback = FormIdeaGenerationCallback(
        results=[FormIdeaGenerationRow.model_validate(r) for r in rows]
    )
    return put_result(callback)


def build() -> StateGraph:
    g: StateGraph = StateGraph(PipelineState)
    g.add_node("plan", plan)
    g.add_node("score_template", score_template)
    g.add_node("aggregate", aggregate)
    g.add_edge(START, "plan")
    g.add_conditional_edges("plan", fan_out, ["score_template"])
    g.add_edge("score_template", "aggregate")
    g.add_edge("aggregate", END)
    return g
