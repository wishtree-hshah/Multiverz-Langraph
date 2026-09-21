"""form_filling_10step workflow.

n8n source: "10 step form filling (3).json" (308 nodes — the largest export,
but most of its bulk is not business logic). Traced node-by-node; see
docs/MIGRATION-FROM-N8N.md.

Graph:

    ingest_documents -> generate_step_1 -> await_approval -> generate_step_2
        -> await_approval -> ... -> generate_step_9 -> await_approval
        -> generate_step_10 -> run_qc_panel --[hasBlockerOrMajor]--> revise_report -\\
                              \\--[else]-------------> finalize_first_pass -> assemble_callback

Traced control flow and scope decisions:

* **~70 nodes** ("Resolve Deps (AI Agent*)", "Fetch Prior (AI Agent*)",
  "Assemble Ctx (AI Agent*)", "Shape Save (AI Agent*)", "Save Output
  (AI Agent*)", "Restore (AI Agent*)", "Delete Prior (AI Agent*)", "Restore
  Doc (AI Agent*)", once per step) are n8n's own durability layer: each
  step's output is written to MongoDB so a crashed execution can resume
  without re-running completed steps. **Not ported** — this is exactly what
  LangGraph's Postgres checkpointer already provides, and better (resumes
  mid-node, not just mid-step).
* **"Resolve Deps (AI Agent*)"** does carry one load-bearing, non-durability
  fact: the per-step dependency map, identical in every copy —
  ``{1:[],2:[1],3:[1,2],4:[3],5:[2,3,4],6:[4,5],7:[1,5,6],8:[7],9:[8],10:[1,4,5]}``.
  Ported verbatim as ``_DEPS``.
* **"Assemble Ctx (AI Agent*)"** appends each dependency's saved output to
  the step's prompt as ``\\n\\n===== OUTPUT OF STEP N =====\\n<json>``, prefixed
  once with ``--- PRIOR STEP OUTPUTS (authoritative context) ---``. Ported
  verbatim in ``_prior_context``.
* **"Code in JavaScript6"** (after step 4) tags the two scenario-framework
  blocks the model returns under keys ``"0"``/``"1"`` with
  ``type``/``axes.method`` = ``GBN`` / ``Four Step``. Ported verbatim as
  ``_tag_scenario_methods``.
* **Per-step JSON-repair agents** — "Format Agent (s5..s9)" plus "AI
  Agent10..14" (general/report/best-practices/signals/scenario-specific
  structure repair) and their "Validate/Route/Regen Prompt" scaffolding —
  are n8n's bespoke version of exactly what ``generate_structured()``
  already does uniformly across every ported stage in this codebase (one
  repair attempt, feeding validation errors back to the same model).
  **Not ported as separate agents** — collapsed into ``generate_structured``'s
  built-in repair, per this repo's own established replacement for every
  n8n ``outputParserStructured`` node (see docs/MIGRATION-FROM-N8N.md). This
  changes the repair *mechanism*, not the *outcome* it aims for.
* **9 "Wait" nodes**, one after each of steps 1-9 (none after step 10, which
  goes straight to the QC panel) — human review/edit gates. Ported as
  ``interrupt()`` at the one node that does nothing else (``await_approval``),
  matching this codebase's existing ``waiting_human`` / resume infra
  (graph/runner.py, api/routes/runs.py) exactly. The resume value's
  ``output`` field, if present, overrides the step's generated output before
  continuing — the human's edit.
* **Per-step checkpoint callback** ("Edit Fields17" -> "HTTP Request5", body
  ``{runId, stepNumber, stepKey, output}``) matches backend's
  ``N8nStepCheckpointDto`` exactly. No separate "final submission" endpoint
  exists on the backend for this workflow — steps 1-9 POST it directly as a
  mid-run side effect (``post_callback`` reused as-is, same body shape);
  step 10's checkpoint **is** the run's normal end-of-run callback delivery
  (``put_result`` -> the queue task's existing single-callback machinery),
  since there is nothing after it to distinguish a separate "submission".
* **QC 1-5 + QC 6 (Revision Agent)** are the *exact same* agent nodes as
  report_render's QC panel (confirmed identical prompt text) — reused here
  via the same ``report_render.qc*`` registry refs and
  ``schemas.report_render`` models rather than re-authoring them. Applied
  once, to step 10's output only (reshaped into report_render's
  ``reportSections`` shape: one "section" per Step 10 key). No QC C1
  (render-conformance) and no post-revision recheck pass here, unlike
  report_render's fuller panel — matching the node list (this export has no
  "QC C1" node and no second QC1/QC2 pass).
* Document ingestion (step 1's ``${documents}``) and web search (step 1's
  explicit Q5/Q10/Q11/Q18 search budget) reuse ``tools.documents`` /
  ``tools.search`` exactly as domain_agent/idea_extraction/report_render do.
  Search is wired for step 1 only — the only step whose prompt names a hard
  search budget tied to specific questions; other steps' looser mentions of
  "web search tool" are answered from the model's own reasoning. A
  documented scope cut, not a silent one.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from strategy_navigator.callbacks.client import post_callback
from strategy_navigator.constants import Workflow
from strategy_navigator.errors import BackendCallbackError
from strategy_navigator.graph.state import PipelineState
from strategy_navigator.llm.structured import generate_structured
from strategy_navigator.logging import get_logger
from strategy_navigator.prompts import bindings, render_prompt
from strategy_navigator.schemas.form_filling import (
    FormFillingRequest,
    Step1Output,
    Step2Output,
    Step3Output,
    Step4Output,
    Step5Output,
    Step6Output,
    Step7Output,
    Step8Output,
    Step9Output,
    Step10Output,
    StepCheckpoint,
)
from strategy_navigator.schemas.report_render import (
    QC1Output,
    QC2Output,
    QC3Output,
    QC4Output,
    QC5Output,
    QC6Output,
)
from strategy_navigator.stages.base import get_request, put_artifact, put_result, stage_node
from strategy_navigator.tools.documents import extract_document_text
from strategy_navigator.tools.search import jina_search

log = get_logger(__name__)

_DEPS: dict[int, list[int]] = {
    1: [],
    2: [1],
    3: [1, 2],
    4: [3],
    5: [2, 3, 4],
    6: [4, 5],
    7: [1, 5, 6],
    8: [7],
    9: [8],
    10: [1, 4, 5],
}
_STEP_SCHEMAS: dict[int, type] = {
    1: Step1Output,
    2: Step2Output,
    3: Step3Output,
    4: Step4Output,
    5: Step5Output,
    6: Step6Output,
    7: Step7Output,
    8: Step8Output,
    9: Step9Output,
    10: Step10Output,
}
_SEV_RANK = {"blocker": 3, "major": 2, "minor": 1}


@stage_node("ingest_documents")
async def ingest_documents(state: PipelineState) -> dict[str, Any]:
    req = get_request(state, FormFillingRequest)
    refs = req.project.documents
    if not refs:
        return put_artifact("documentSummary", "")

    async def summarise(ref: str) -> str:
        try:
            text = await extract_document_text(ref)
        except Exception as exc:  # a bad doc must not sink the run
            log.warning("form_filling_10step.doc_failed", ref=ref, error=str(exc))
            return ""
        return text[:8000]

    summaries = await asyncio.gather(*(summarise(r) for r in refs))
    return put_artifact("documentSummary", "\n\n".join(s for s in summaries if s))


def _prior_context(state: PipelineState, n: int) -> str:
    parts = []
    for dep in _DEPS[n]:
        out = state["artifacts"].get(f"step_{dep}")
        if out is not None:
            parts.append(
                f"\n\n===== OUTPUT OF STEP {dep} =====\n{json.dumps(out, ensure_ascii=False)}"
            )
    if not parts:
        return ""
    return "\n\n--- PRIOR STEP OUTPUTS (authoritative context) ---" + "".join(parts)


def _tag_scenario_methods(output: dict[str, Any]) -> None:
    """Port of "Code in JavaScript6" — runs after step 4 only."""
    zero = output.get("0")
    if zero:
        zero["type"] = "GBN"
        zero.setdefault("axes", {})["method"] = "GBN"
    one = output.get("1")
    if one:
        one["type"] = "Four Step"
        one.setdefault("axes", {})["method"] = "Four Step"


async def _step1_research(req: FormFillingRequest) -> str:
    queries = [
        f"{req.project.project_name} current situation {req.project.client_organization}",
        f"{req.project.project_name} analogous problems case studies",
        f"{req.project.project_description} available research information",
        f"how others solved {req.project.project_name} similar problems",
    ]
    results = await asyncio.gather(
        *(jina_search(q, top_k=3) for q in queries), return_exceptions=True
    )
    hits: list[str] = []
    for r in results:
        if isinstance(r, BaseException):
            log.warning("form_filling_10step.search_failed", error=str(r))
            continue
        hits.extend(f"- {h.title}: {h.snippet} ({h.url})" for h in r)
    return "\n".join(hits[:20])


async def _generate_step(state: PipelineState, n: int) -> dict[str, Any]:
    req = get_request(state, FormFillingRequest)
    prompt_vars = bindings.build(
        req.project, agent=req.agent, document_summary=state["artifacts"].get("documentSummary", "")
    )
    system = render_prompt(f"form_filling_10step.step_{n}", **prompt_vars)
    system += _prior_context(state, n)
    if n == 1:
        research = state["artifacts"].get("research", "")
        if research:
            system += f"\n\n--- WEB SEARCH RESULTS (for Q5, Q10, Q11, Q18) ---\n{research}"

    schema = _STEP_SCHEMAS[n]
    output: Any = await generate_structured(
        schema,
        [{"role": "system", "content": system}],
        stage=f"step_{n}",
        temperature=0.4,
        max_tokens=6000,
    )
    output_dict = output.model_dump(by_alias=True)
    if n == 4:
        _tag_scenario_methods(output_dict)
    return output_dict


def _make_generate_step(n: int) -> Any:
    async def _node(state: PipelineState) -> dict[str, Any]:
        if n == 1:
            req = get_request(state, FormFillingRequest)
            research = await _step1_research(req)
            state = {**state, "artifacts": {**state["artifacts"], "research": research}}

        output = await _generate_step(state, n)
        updates: dict[str, Any] = {f"step_{n}": output, "lastCompletedStep": n}

        if n < 10:  # step 10's checkpoint is the run's normal final delivery instead
            req = get_request(state, FormFillingRequest)
            checkpoint = StepCheckpoint(
                run_id=state["run_id"], step_number=n, step_key=f"step{n}", output=output
            )
            try:
                await post_callback(
                    workflow=str(Workflow.FORM_FILLING_10STEP),
                    callback_url=req.callback_url,
                    session_id=req.session_id,
                    body=checkpoint.model_dump(by_alias=True, exclude_none=True),
                )
            except BackendCallbackError as exc:
                log.warning("form_filling_10step.checkpoint_failed", step=n, error=str(exc))

        return {"artifacts": updates}

    return stage_node(f"generate_step_{n}")(_node)


_GENERATE_STEP_NODES = {n: _make_generate_step(n) for n in range(1, 11)}


@stage_node("await_approval")
async def await_approval(state: PipelineState) -> dict[str, Any]:
    """The one node in the human-gate that calls ``interrupt()`` — kept free of
    every other side effect (LLM calls, HTTP posts), since LangGraph re-runs a
    node's body from the top on resume and only the interrupt() calls
    themselves replay from cache, not ordinary statements before them.

    The ``POST /runs/{run_id}/resume`` caller (``api/routes/runs.py``) must
    send a **non-empty** ``value`` — ``{"approved": true}`` to accept the step
    as-is, or ``{"output": {...edited step output...}}`` to override it.
    LangGraph treats an empty/falsy resume value as "nothing to resume with"
    and re-issues the same interrupt rather than continuing.
    """
    n = state["artifacts"]["lastCompletedStep"]
    output = state["artifacts"][f"step_{n}"]
    resume = interrupt({"stepNumber": n, "stepKey": f"step{n}", "output": output})
    if isinstance(resume, dict) and resume.get("output") is not None:
        return {"artifacts": {f"step_{n}": resume["output"]}}
    return {}


def route_after_approval(state: PipelineState) -> str:
    n = state["artifacts"]["lastCompletedStep"]
    return f"generate_step_{n + 1}"


def _step10_as_sections(step10: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "sectionName": key,
            "content": value or "",
            "citationKeysUsed": [],
            "factIdsUsed": [],
            "externalOptionIdsUsed": [],
            "unfillable": not bool(value),
            "wordCount": len((value or "").split()),
        }
        for key, value in step10.items()
    ]


async def _qc_critic(
    ref: str, schema: type, var_name: str, payload: dict[str, Any], stage: str
) -> Any:
    system = render_prompt(ref, **{var_name: json.dumps(payload, ensure_ascii=False)})
    return await generate_structured(
        schema, [{"role": "system", "content": system}], stage=stage, temperature=0.2
    )


def _consolidate_findings(critic_outputs: list[dict[str, Any]]) -> dict[str, Any]:
    """Reduced version of report_render's Consolidate Findings 1 — this panel
    has no render_conformance (QC C1) critic."""
    all_findings: list[dict[str, Any]] = []
    for out in critic_outputs:
        critic = out.get("critic")
        if critic in ("traceability_auditor", "coherence_checker", "red_team"):
            all_findings.extend({**f, "critic": critic} for f in out.get("findings", []))
        elif critic == "surprise_genericity_scorer":
            all_findings.extend(
                {**f, "critic": critic} for f in out.get("mostGenericParagraphs", [])
            )
        elif critic == "reader_persona_panel":
            all_findings.extend({**f, "critic": critic} for f in out.get("convergentIssues", []))

    by_signature: dict[str, dict[str, Any]] = {}
    for f in all_findings:
        quote = f.get("quote") or f.get("targetClaim") or f.get("quoteA") or ""
        section = f.get("sectionName") or (f.get("sectionNames") or [""])[0]
        key = f"{section}::{quote}"
        existing = by_signature.get(key)
        if not existing or _SEV_RANK.get(f.get("severity", ""), 0) > _SEV_RANK.get(
            existing.get("severity", ""), 0
        ):
            by_signature[key] = f

    consolidated = list(by_signature.values())
    has_blocker_or_major = any(f.get("severity") in ("blocker", "major") for f in consolidated)
    protection_list: list[Any] = next(
        (
            o.get("protectionList", [])
            for o in critic_outputs
            if o.get("critic") == "surprise_genericity_scorer"
        ),
        [],
    )
    return {
        "consolidatedFindings": consolidated,
        "hasBlockerOrMajor": has_blocker_or_major,
        "protectionList": protection_list,
    }


@stage_node("run_qc_panel")
async def run_qc_panel(state: PipelineState) -> dict[str, Any]:
    sections = _step10_as_sections(state["artifacts"]["step_10"])
    engagement_context = {f"step{n}": state["artifacts"].get(f"step_{n}") for n in range(1, 10)}

    qc1, qc2, qc3, qc4, qc5 = await asyncio.gather(
        _qc_critic(
            "report_render.qc1_traceability",
            QC1Output,
            "qc1_input",
            {
                "reportSections": sections,
                "substrateExtracts": engagement_context,
                "engagementInputs": {},
                "mechanicalDefects": [],
            },
            "ff_qc1",
        ),
        _qc_critic(
            "report_render.qc2_coherence",
            QC2Output,
            "qc2_input",
            {"reportSections": sections, "renderPlan": {}, "substrateExtracts": engagement_context},
            "ff_qc2",
        ),
        _qc_critic(
            "report_render.qc3_reader_panel",
            QC3Output,
            "qc3_input",
            {"reportSections": sections, "engagementInputs": {}, "agentProfile": {}},
            "ff_qc3",
        ),
        _qc_critic(
            "report_render.qc4_red_team",
            QC4Output,
            "qc4_input",
            {
                "reportSections": sections,
                "substrateExtracts": engagement_context,
                "engagementInputs": {},
            },
            "ff_qc4",
        ),
        _qc_critic(
            "report_render.qc5_genericity",
            QC5Output,
            "qc5_input",
            {"reportSections": sections, "renderPlan": {}, "engagementInputs": {}},
            "ff_qc5",
        ),
    )
    critic_outputs = [o.model_dump(by_alias=True) for o in (qc1, qc2, qc3, qc4, qc5)]
    consolidated = _consolidate_findings(critic_outputs)
    return put_artifact("qcFirstPass", {"criticOutputs": critic_outputs, **consolidated})


def fan_out_revision(state: PipelineState) -> str:
    return (
        "revise_report"
        if state["artifacts"]["qcFirstPass"]["hasBlockerOrMajor"]
        else "finalize_first_pass"
    )


@stage_node("revise_report")
async def revise_report(state: PipelineState) -> dict[str, Any]:
    first_pass = state["artifacts"]["qcFirstPass"]
    sections = _step10_as_sections(state["artifacts"]["step_10"])
    # No archetype/word-budget concept in this workflow — a generous synthetic
    # render plan so the revision agent's word-budget checks never block it.
    render_plan = {
        "sections": [
            {
                "sectionName": s["sectionName"],
                "wordTarget": s["wordCount"],
                "toleranceBand": [0, 999999],
            }
            for s in sections
        ]
    }
    qc6_input = {
        "reportSections": sections,
        "renderPlan": render_plan,
        "consolidatedFindings": first_pass["consolidatedFindings"],
        "criticOutputs": first_pass["criticOutputs"],
        "protectionList": first_pass["protectionList"],
    }
    output = await _qc_critic(
        "report_render.qc6_revision", QC6Output, "qc6_input", qc6_input, "ff_revise"
    )
    revision = output.model_dump(by_alias=True)
    revised_step10 = {s["sectionName"]: s["content"] for s in revision["revisedSections"]}
    return {"artifacts": {"step_10": revised_step10, "qcRevised": True}}


@stage_node("finalize_first_pass")
async def finalize_first_pass(state: PipelineState) -> dict[str, Any]:
    return put_artifact("qcRevised", False)


@stage_node("assemble_callback")
async def assemble_callback(state: PipelineState) -> dict[str, Any]:
    checkpoint = StepCheckpoint(
        run_id=state["run_id"],
        step_number=10,
        step_key="step10",
        output=state["artifacts"]["step_10"],
    )
    return put_result(checkpoint)


def build() -> StateGraph:
    g: StateGraph = StateGraph(PipelineState)
    g.add_node("ingest_documents", ingest_documents)
    for n in range(1, 11):
        g.add_node(f"generate_step_{n}", _GENERATE_STEP_NODES[n])
    g.add_node("await_approval", await_approval)
    g.add_node("run_qc_panel", run_qc_panel)
    g.add_node("revise_report", revise_report)
    g.add_node("finalize_first_pass", finalize_first_pass)
    g.add_node("assemble_callback", assemble_callback)

    g.add_edge(START, "ingest_documents")
    g.add_edge("ingest_documents", "generate_step_1")
    for n in range(1, 10):
        g.add_edge(f"generate_step_{n}", "await_approval")
    g.add_conditional_edges(
        "await_approval", route_after_approval, [f"generate_step_{n}" for n in range(2, 11)]
    )
    g.add_edge("generate_step_10", "run_qc_panel")
    g.add_conditional_edges(
        "run_qc_panel", fan_out_revision, ["revise_report", "finalize_first_pass"]
    )
    g.add_edge("revise_report", "assemble_callback")
    g.add_edge("finalize_first_pass", "assemble_callback")
    g.add_edge("assemble_callback", END)
    return g
