"""domain_agent workflow  (reference implementation).

n8n source: "Domain Specific Agent (1).json" (75 nodes).

Graph:
    START -> ingest_documents -> generate_personas -> assemble_callback -> END

* ingest_documents  : fetch + summarise each background doc (parallel), so the
  persona generation prompt has the same context the n8n summariser chains built.
* generate_personas : one structured LLM call -> DomainAgentOutput.
* assemble_callback : shape the DomainAgentCallback body the backend expects.
"""

from __future__ import annotations

import asyncio
from typing import Any

from langgraph.graph import END, START, StateGraph

from strategy_navigator.graph.state import PipelineState
from strategy_navigator.llm.structured import generate_structured
from strategy_navigator.logging import get_logger
from strategy_navigator.prompts import bindings, render, render_prompt
from strategy_navigator.schemas.domain import (
    DomainAgentCallback,
    DomainAgentOutput,
    DomainAgentRequest,
)
from strategy_navigator.stages.base import get_request, put_artifact, put_result, stage_node
from strategy_navigator.tools.documents import extract_document_text

log = get_logger(__name__)


@stage_node("ingest_documents")
async def ingest_documents(state: PipelineState) -> dict[str, Any]:
    req = get_request(state, DomainAgentRequest)
    refs = [d.key for d in req.documents] or req.project.documents
    if not refs:
        return put_artifact("document_summary", "")

    async def summarise(ref: str) -> str:
        try:
            text = await extract_document_text(ref)
        except Exception as exc:  # a bad doc must not sink the run
            log.warning("domain_agent.doc_failed", ref=ref, error=str(exc))
            return ""
        if not text.strip():
            return ""
        result = await _summariser(text)
        return result

    summaries = await asyncio.gather(*(summarise(r) for r in refs))
    merged = "\n\n".join(s for s in summaries if s)
    return put_artifact("document_summary", merged)


async def _summariser(content: str) -> str:
    from strategy_navigator.llm.client import get_llm

    prompt = render_prompt("_shared.summarizer", content=content[:40_000])
    res = await get_llm().chat(
        [{"role": "user", "content": prompt}], fast=True, stage="ingest_documents"
    )
    return res.text.strip()


@stage_node("generate_personas")
async def generate_personas(state: PipelineState) -> dict[str, Any]:
    req = get_request(state, DomainAgentRequest)
    prompt_vars = bindings.build(
        req.project,
        document_summary=state["artifacts"].get("document_summary", ""),
        min_agents=req.min_agents,
        max_agents=req.max_agents,
    )
    system = render_prompt("domain_agent.system", **prompt_vars)
    output = await generate_structured(
        DomainAgentOutput,
        [
            {"role": "system", "content": system},
            {"role": "user", "content": render("domain_agent.user", **prompt_vars)},
        ],
        stage="generate_personas",
        temperature=0.4,
    )
    return put_artifact("personas", output.model_dump())


@stage_node("assemble_callback")
async def assemble_callback(state: PipelineState) -> dict[str, Any]:
    req = get_request(state, DomainAgentRequest)
    output = DomainAgentOutput.model_validate(state["artifacts"]["personas"])
    callback = DomainAgentCallback(
        session_id=req.session_id,
        project_id=req.project.project_id,
        agents=output.personas,
        execution_id=state["run_id"],
    )
    return put_result(callback)


def build() -> StateGraph:
    g: StateGraph = StateGraph(PipelineState)
    g.add_node("ingest_documents", ingest_documents)
    g.add_node("generate_personas", generate_personas)
    g.add_node("assemble_callback", assemble_callback)
    g.add_edge(START, "ingest_documents")
    g.add_edge("ingest_documents", "generate_personas")
    g.add_edge("generate_personas", "assemble_callback")
    g.add_edge("assemble_callback", END)
    return g
