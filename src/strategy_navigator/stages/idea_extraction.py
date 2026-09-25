"""idea_extraction workflow  (reference implementation).

n8n source: "Agent Idea Extraction with Project (2).json" (63 nodes).

Graph:
    START -> research -> generate_ideas -> assemble_callback -> END

* research       : run the agent's research queries through Jina (cached),
  collect hits to ground the ideas' `sources`.
* generate_ideas : one structured call in the agent's persona -> IdeaExtractionOutput.
* assemble_callback : IdeaExtractionCallback with agentId provenance.
"""

from __future__ import annotations

import asyncio
from typing import Any

from langgraph.graph import END, START, StateGraph

from strategy_navigator.graph.state import PipelineState
from strategy_navigator.llm.structured import generate_structured
from strategy_navigator.logging import get_logger
from strategy_navigator.prompts import bindings, render, render_prompt
from strategy_navigator.schemas.ideas import (
    ExtractedIdea,
    IdeaExtractionCallback,
    IdeaExtractionOutput,
    IdeaExtractionRequest,
)
from strategy_navigator.stages.base import get_request, put_artifact, put_result, stage_node
from strategy_navigator.tools.search import jina_search

log = get_logger(__name__)


@stage_node("research")
async def research(state: PipelineState) -> dict[str, Any]:
    req = get_request(state, IdeaExtractionRequest)
    queries = req.research_queries or _default_queries(req)
    if not queries:
        return put_artifact("research", [])

    results = await asyncio.gather(
        *(jina_search(q, top_k=4) for q in queries[:5]), return_exceptions=True
    )
    hits: list[dict[str, str]] = []
    for r in results:
        if isinstance(r, BaseException):
            log.warning("idea_extraction.search_failed", error=str(r))
            continue
        hits.extend({"title": h.title, "url": h.url, "snippet": h.snippet} for h in r)
    # de-dupe by url
    seen: set[str] = set()
    deduped = [h for h in hits if h["url"] and not (h["url"] in seen or seen.add(h["url"]))]
    return put_artifact("research", deduped[:12])


def _default_queries(req: IdeaExtractionRequest) -> list[str]:
    p = req.project
    base = f"{p.project_name} {p.client_organization}".strip()
    return [f"{base} strategy trends", f"{base} {req.agent.designation or 'industry'} outlook"]


@stage_node("generate_ideas")
async def generate_ideas(state: PipelineState) -> dict[str, Any]:
    req = get_request(state, IdeaExtractionRequest)
    prompt_vars = bindings.build(
        req.project,
        agent=req.agent,
        research=state["artifacts"].get("research", []),
        idea_count=req.idea_count,
        categories=req.categories,
        previous_agent_ideas="",
    )
    system = render_prompt("idea_extraction.system", **prompt_vars)
    output = await generate_structured(
        IdeaExtractionOutput,
        [
            {"role": "system", "content": system},
            {"role": "user", "content": render("idea_extraction.user", **prompt_vars)},
        ],
        stage="generate_ideas",
        temperature=0.6,
    )
    return put_artifact("ideas", output.model_dump())


@stage_node("assemble_callback")
async def assemble_callback(state: PipelineState) -> dict[str, Any]:
    req = get_request(state, IdeaExtractionRequest)
    output = IdeaExtractionOutput.model_validate(state["artifacts"]["ideas"])
    results = [
        ExtractedIdea(
            title=i.title,
            summary=i.summary,
            sources=i.sources,
            categories=i.categories or req.categories,
        )
        for i in output.ideas
    ]
    callback = IdeaExtractionCallback(
        run_id=req.session_id,
        agent_id=req.agent.id,
        agent_source="domain-specific" if req.agent.is_domain_specific else None,
        results=results,
    )
    return put_result(callback)


def build() -> StateGraph:
    g: StateGraph = StateGraph(PipelineState)
    g.add_node("research", research)
    g.add_node("generate_ideas", generate_ideas)
    g.add_node("assemble_callback", assemble_callback)
    g.add_edge(START, "research")
    g.add_edge("research", "generate_ideas")
    g.add_edge("generate_ideas", "assemble_callback")
    g.add_edge("assemble_callback", END)
    return g
