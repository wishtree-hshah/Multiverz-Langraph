"""rapid_consolidation workflow.

n8n source: "Rapid Insight - Consolidation Agent.json" (58 nodes). Three
sequential Mongo-backed calls (consolidation_a/b/c, already pulled to
prompts/_mongo/):

    START -> revise_existing -> consolidate_documents -> surface_new_ideas
          -> assemble_callback -> END

Traced directly from the n8n Code nodes (the JSON export, unlike the prompt
wording, IS checked in) rather than guessed from the prompt text alone:

* ``existing_ideas_with_comments`` (Call A / "revise_existing") — every idea
  across all agent groups whose ``type != "human"`` (node "Code in JavaScript4").
* ``document_comments`` (Call B / "consolidate_documents") — the inbound
  ``documentComments[]`` reshaped to ``{document, comments}`` (node
  "Code in JavaScript5").
* ``ideator_new_ideas`` (Call C / "surface_new_ideas") — ideas with
  ``type == "human"`` from agent groups where ``isDomainSpecific is False``
  (node "Code in JavaScript6"); ``document_idea_candidates`` is Call B's
  ``idea_candidates``; ``revised_existing_ideas`` is Call A's raw output,
  passed through read-only.
* The final callback's ``ideas`` = Call A's revised ideas + Call C's new
  ideas, each idea's ``agentId``/``isDomainSpecificAgent`` resolved by exact
  **title match** against the original inbound ``agents[].ideas[].title``
  (node "Code in JavaScript7") — unmatched titles (genuinely new ideas) get
  ``agentId: null``, exactly as n8n's ``titleToAgent[idea.title] || {agentId:
  null, ...}`` fallback does.
"""

from __future__ import annotations

import json
from typing import Any

from langgraph.graph import END, START, StateGraph

from strategy_navigator.graph.state import PipelineState
from strategy_navigator.llm.structured import generate_structured
from strategy_navigator.prompts import bindings, render_prompt
from strategy_navigator.schemas.common import Idea
from strategy_navigator.schemas.consolidation import (
    ConsolidatedIdea,
    ConsolidationCallback,
    ConsolidationRequest,
    DocumentCommentaryOutput,
    RevisedIdeasOutput,
)
from strategy_navigator.stages.base import get_request, put_artifact, put_result, stage_node


@stage_node("revise_existing")
async def revise_existing(state: PipelineState) -> dict[str, Any]:
    req = get_request(state, ConsolidationRequest)
    existing = [
        {
            "agentName": agent.name,
            "agentType": agent.agent_type,
            "title": idea.title,
            "summary": idea.summary,
            "sources": idea.sources,
            "categories": idea.categories,
            "comments": idea.comments,
        }
        for agent in req.agents
        for idea in agent.ideas
        if idea.type != "human"
    ]
    prompt_vars = bindings.build(
        req.project, existing_ideas_with_comments=json.dumps(existing, ensure_ascii=False)
    )
    system = render_prompt("rapid_consolidation.a", **prompt_vars)
    output = await generate_structured(
        RevisedIdeasOutput,
        [{"role": "system", "content": system}],
        stage="revise_existing",
        temperature=0.2,
    )
    return put_artifact("revised_existing_ideas", [i.model_dump() for i in output.ideas])


@stage_node("consolidate_documents")
async def consolidate_documents(state: PipelineState) -> dict[str, Any]:
    req = get_request(state, ConsolidationRequest)
    document_comments = [
        {"document": dc.document_key, "comments": dc.comments} for dc in req.document_comments
    ]
    prompt_vars = bindings.build(
        req.project, document_comments=json.dumps(document_comments, ensure_ascii=False)
    )
    system = render_prompt("rapid_consolidation.b", **prompt_vars)
    output = await generate_structured(
        DocumentCommentaryOutput,
        [{"role": "system", "content": system}],
        stage="consolidate_documents",
        temperature=0.2,
    )
    return put_artifact("document_commentary", output.model_dump())


@stage_node("surface_new_ideas")
async def surface_new_ideas(state: PipelineState) -> dict[str, Any]:
    req = get_request(state, ConsolidationRequest)
    ideator_new_ideas = [
        {
            "title": idea.title,
            "summary": idea.summary,
            "sources": idea.sources,
            "categories": idea.categories,
        }
        for agent in req.agents
        if agent.is_domain_specific is False
        for idea in agent.ideas
        if idea.type == "human"
    ]
    document_idea_candidates = state["artifacts"]["document_commentary"]["idea_candidates"]
    revised_existing_ideas = state["artifacts"]["revised_existing_ideas"]
    prompt_vars = bindings.build(
        req.project,
        ideator_new_ideas=json.dumps(ideator_new_ideas, ensure_ascii=False),
        document_idea_candidates=json.dumps(document_idea_candidates, ensure_ascii=False),
        revised_existing_ideas=json.dumps(revised_existing_ideas, ensure_ascii=False),
    )
    system = render_prompt("rapid_consolidation.c", **prompt_vars)
    output = await generate_structured(
        RevisedIdeasOutput,
        [{"role": "system", "content": system}],
        stage="surface_new_ideas",
        temperature=0.2,
    )
    return put_artifact("new_ideas", [i.model_dump() for i in output.ideas])


@stage_node("assemble_callback")
async def assemble_callback(state: PipelineState) -> dict[str, Any]:
    req = get_request(state, ConsolidationRequest)

    title_to_agent: dict[str, tuple[int, bool]] = {}
    for agent in req.agents:
        for idea in agent.ideas:
            title_to_agent[idea.title] = (agent.id, agent.is_domain_specific)

    combined = state["artifacts"]["revised_existing_ideas"] + state["artifacts"]["new_ideas"]
    mapped: list[Idea] = []
    for item in combined:
        agent_id, is_domain_specific = title_to_agent.get(item["title"], (None, None))
        mapped.append(
            Idea.model_validate(
                ConsolidatedIdea(
                    title=item["title"],
                    summary=item["summary"],
                    sources=item.get("sources", []),
                    categories=item.get("categories", []),
                    agent_id=agent_id,
                    is_domain_specific_agent=is_domain_specific,
                    tier=item.get("tier"),
                ).model_dump()
            )
        )

    callback = ConsolidationCallback(
        session_id=req.session_id,
        ideas=mapped,
        execution_id=state["run_id"],
        consolidation_type=req.consolidation_type,
    )
    return put_result(callback)


def build() -> StateGraph:
    g: StateGraph = StateGraph(PipelineState)
    g.add_node("revise_existing", revise_existing)
    g.add_node("consolidate_documents", consolidate_documents)
    g.add_node("surface_new_ideas", surface_new_ideas)
    g.add_node("assemble_callback", assemble_callback)
    g.add_edge(START, "revise_existing")
    g.add_edge("revise_existing", "consolidate_documents")
    g.add_edge("consolidate_documents", "surface_new_ideas")
    g.add_edge("surface_new_ideas", "assemble_callback")
    g.add_edge("assemble_callback", END)
    return g
