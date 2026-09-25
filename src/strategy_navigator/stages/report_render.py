"""report_render workflow.

n8n source: "Report Render (3).json" (114 nodes). Traced node-by-node from the
export's actual Code/If/connections (not just the inline prompt text, which
alone does not carry the control flow) — see docs/MIGRATION-FROM-N8N.md and
the notes below.

Graph:

    detect_gaps -> search_external -> plan_render -> plan_fact_currency
        -> generate_sections -> edit_sections -> run_mechanical_audit
        -> run_qc_panel --[hasBlockerOrMajor]--> revise_report -> recheck_qc -\\
                        \\--[else]-----------> finalize_first_pass ------------> score_and_gate
        -> assemble_callback

Traced control flow (node names as in the n8n export):

* **(Node 18) Length Branch** routes section generation long (>15 pages,
  per-section loop) vs short (one batch call). Ported as the short/batch
  path only — a single ``generate_structured`` call handles both cases
  correctly, just less token-efficiently for very long reports; this is a
  documented scope cut, not a silent one.
* **EDITORIAL** runs once per section; node **If** checks the result for an
  empty/short (<100 word) output and retries once via **EDITORIAL3** — a
  byte-identical prompt, n8n's own retry-node pattern. Ported as one prompt
  called up to twice per section (see ``_edit_one``).
* **AUDIT Input / AUDIT Input1** (mechanical, deterministic, no LLM) verify
  every ``factId``/``sourceId``/``externalOptionId`` a section declares
  actually exists in the substrate, and that a declared figure's value
  literally appears in the prose. Ported faithfully as ``_mechanical_audit``.
  n8n computes a ``routeTo: 'section_generation'`` retry field on failure but
  no If/Switch node in the export actually acts on it — so no automatic
  regeneration loop is wired here either, matching real behaviour.
* **(Node 17) Search Execution** is a pure data-passthrough Code node in the
  export (repackages Node 16's queries; no search call is wired to it).
  Ported the same way — ``fact_currency_planning``'s queries are produced but
  not executed against a search API, exactly as n8n does today.
* **Node 13** (external search) has a real web-search tool attached; ported
  using ``tools.search.jina_search`` (already Postgres-cached) to gather
  results, which are then composed into the structured-output call, rather
  than an agentic tool-calling loop.
* **Consolidate Findings 1** (node "Consolidate Findings 1") computes
  ``hasBlockerOrMajor`` by deduplicating findings across all 6 first-pass
  critics by ``(sectionName, quote)``, keeping the higher-severity copy.
  Ported verbatim in ``_consolidate_findings_1``. **If2** gates the whole
  revision+recheck branch on this flag — a report with no blocker/major
  findings skips QC 6 and the recheck entirely (n8n allows at most one
  revision cycle; there is no loop back to the first-pass critics).
* **Code in JavaScript9** (final assembly) renumbers ``(S001, S002)``
  citation markers into ``[1][2]`` footnotes in order of first appearance,
  assembles the Markdown report, and computes ``status`` from the mechanical
  audit + QC gate. Ported verbatim in ``_assemble_report_markdown`` /
  ``assemble_callback``.
* Pre-specified archetype definitions (their sectionList, wordsPerPage, etc.
  for the 9 built-in archetypes) live outside the git-tracked n8n export —
  only a *custom* archetype carries ``archetypeDefinition`` inline in the
  trigger payload (see ``CapstoneRenderTriggerPayload``/
  ``SelectedArchetypeEntryDto`` in challenges-backend). ``_archetype()``
  falls back to a minimal definition from the archetype key + the
  name/template map lifted from "Code in JavaScript9" so the stage degrades
  gracefully rather than failing outright; this is a known gap, not a
  guess dressed up as fidelity.

Internal artifacts in this stage use **camelCase keys** throughout (matching
the n8n JS this was ported from, and the prompts' own JSON contracts) rather
than this codebase's usual snake_case — with 14 chained prompt calls each
feeding the next, staying in one casing avoids constant re-keying.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from langgraph.graph import END, START, StateGraph

from strategy_navigator.graph.state import PipelineState
from strategy_navigator.llm.structured import generate_structured
from strategy_navigator.logging import get_logger
from strategy_navigator.prompts import render_prompt
from strategy_navigator.schemas.capstone import RenderCallback, RenderRequest
from strategy_navigator.schemas.report_render import (
    ExternalSearchOutput,
    FactCurrencyOutput,
    GapDetectionOutput,
    QC1Output,
    QC2Output,
    QC3Output,
    QC4Output,
    QC5Output,
    QC6Output,
    QC7Output,
    QCC1Output,
    RenderedSection,
    RenderPlanOutput,
    SectionGenerationOutput,
)
from strategy_navigator.stages.base import get_request, put_artifact, put_result, stage_node
from strategy_navigator.tools.search import jina_search

log = get_logger(__name__)

_WORDS_PER_PAGE = {"Brief": 450, "Report": 400, "Workshop": 300}
_TEMPLATE_MAP = {
    "decision-brief": "Brief",
    "board-paper": "Brief",
    "concept-note": "Brief",
    "strategy-document": "Report",
    "scenario-report": "Report",
    "policy-brief": "Brief",
    "investment-case": "Report",
    "project-brief": "Report",
    "workshop-pack": "Workshop",
    "trends-watch": "Report",
}
_NAME_MAP = {
    "decision-brief": "Decision brief",
    "board-paper": "Board or cabinet paper",
    "concept-note": "Concept note",
    "strategy-document": "Strategy document",
    "scenario-report": "Scenario report",
    "policy-brief": "Policy brief",
    "investment-case": "Investment case",
    "project-brief": "Project brief",
    "workshop-pack": "Workshop pack",
    "trends-watch": "Trends watch",
}
_SEV_RANK = {"blocker": 3, "major": 2, "minor": 1}
_SUBSTRATE_EXTRACT_KEYS = (
    "facts",
    "settledRecommendations",
    "uncertainties",
    "signals",
    "trends",
    "scenarios",
    "bestPractices",
    "externalOptions",
    "existenceProofs",
    "investmentEnvelopes",
    "investmentSummary",
    "provocations",
    "minorityPositions",
    "preferredFuture",
    "stakeholderLensMap",
    "divergence",
    "citations",
)


def _archetype(req: RenderRequest) -> dict[str, Any]:
    entry = (req.selected_archetypes or [{}])[0]
    key = entry.get("archetypeKey", "")
    definition = dict(entry.get("archetypeDefinition") or {})
    template = definition.get("template") or _TEMPLATE_MAP.get(key, "Report")
    definition.setdefault("template", template)
    definition.setdefault("name", _NAME_MAP.get(key, key))
    definition.setdefault("wordsPerPage", _WORDS_PER_PAGE.get(template, 400))
    definition.setdefault("sectionList", [])
    definition.setdefault("searchBudget", 5)
    return {"key": key, "requestedPages": entry.get("requestedPages", 10), "definition": definition}


def _substrate_extracts(substrate: dict[str, Any]) -> dict[str, Any]:
    return {k: substrate[k] for k in _SUBSTRATE_EXTRACT_KEYS if k in substrate}


def _substrate_summary(substrate: dict[str, Any]) -> dict[str, Any]:
    return {
        k: len(v) if isinstance(v, list) else bool(v)
        for k, v in _substrate_extracts(substrate).items()
    }


async def _critic(
    ref: str, schema: type, var_name: str, payload: dict[str, Any], stage: str
) -> Any:
    system = render_prompt(ref, **{var_name: json.dumps(payload, ensure_ascii=False)})
    return await generate_structured(
        schema, [{"role": "system", "content": system}], stage=stage, temperature=0.2
    )


@stage_node("detect_gaps")
async def detect_gaps(state: PipelineState) -> dict[str, Any]:
    req = get_request(state, RenderRequest)
    node12_input = {
        "engagementInputs": {"project": req.project.model_dump(by_alias=True)},
        "substrate": _substrate_extracts(req.substrate),
    }
    system = render_prompt(
        "report_render.gap_detection", node12_input=json.dumps(node12_input, ensure_ascii=False)
    )
    output = await generate_structured(
        GapDetectionOutput,
        [{"role": "system", "content": system}],
        stage="detect_gaps",
        temperature=0.3,
    )
    return put_artifact("gaps", output.model_dump(by_alias=True))


@stage_node("search_external")
async def search_external(state: PipelineState) -> dict[str, Any]:
    req = get_request(state, RenderRequest)
    archetype = _archetype(req)
    gaps = state["artifacts"]["gaps"]["namedGaps"]
    searchable = [g for g in gaps if g.get("searchable", True)]
    budget = archetype["definition"].get("searchBudget", 5)
    queried = searchable[:budget]

    results = await asyncio.gather(
        *(jina_search(g["description"], top_k=3) for g in queried), return_exceptions=True
    )
    retrieved: list[dict[str, Any]] = []
    for gap, r in zip(queried, results, strict=True):
        if isinstance(r, BaseException):
            log.warning("report_render.search_failed", gap_id=gap.get("gapId"), error=str(r))
            continue
        retrieved.append(
            {
                "gapId": gap["gapId"],
                "hits": [{"title": h.title, "url": h.url, "snippet": h.snippet} for h in r],
            }
        )

    node13_input = {
        "namedGaps": gaps,
        "engagementInputs": {"project": req.project.model_dump(by_alias=True)},
        "eligibleClaims": {
            "provocations": req.substrate.get("provocations", []),
            "stretchVariants": [
                r.get("stretchVariant")
                for r in req.substrate.get("settledRecommendations", [])
                if r.get("stretchVariant")
            ],
        },
        "retrievedResults": retrieved,
    }
    output = await _critic(
        "report_render.external_search",
        ExternalSearchOutput,
        "node13_input",
        node13_input,
        "search_external",
    )
    return put_artifact("external", output.model_dump(by_alias=True))


@stage_node("plan_render")
async def plan_render(state: PipelineState) -> dict[str, Any]:
    req = get_request(state, RenderRequest)
    archetype = _archetype(req)
    node15_input = {
        "archetypeDefinition": archetype["definition"],
        "requestedPages": archetype["requestedPages"],
        "substrateSummary": _substrate_summary(req.substrate),
    }
    output = await _critic(
        "report_render.render_planning",
        RenderPlanOutput,
        "node15_input",
        node15_input,
        "plan_render",
    )
    return put_artifact("renderPlan", output.model_dump(by_alias=True)["renderPlan"])


@stage_node("plan_fact_currency")
async def plan_fact_currency(state: PipelineState) -> dict[str, Any]:
    req = get_request(state, RenderRequest)
    node16_input = {
        "renderPlan": state["artifacts"]["renderPlan"],
        "factsRegister": req.substrate.get("facts", []),
        "investmentEnvelopes": req.substrate.get("investmentEnvelopes", []),
    }
    output = await _critic(
        "report_render.fact_currency_planning",
        FactCurrencyOutput,
        "node16_input",
        node16_input,
        "plan_fact_currency",
    )
    # Node 17 "Search Execution" is a pure passthrough in the n8n export (no
    # search actually runs against these queries) — mirrored here.
    return put_artifact("factCurrency", output.model_dump(by_alias=True))


@stage_node("generate_sections")
async def generate_sections(state: PipelineState) -> dict[str, Any]:
    req = get_request(state, RenderRequest)
    render_plan = state["artifacts"]["renderPlan"]
    external = state["artifacts"]["external"]
    node19_input = {
        "sections": render_plan["sections"],
        "renderPlan": render_plan,
        "substrate": _substrate_extracts(req.substrate),
        "externalOptions": external.get("externalOptions", []),
        "existenceProofs": external.get("existenceProofs", []),
    }
    system = render_prompt(
        "report_render.section_generation",
        node19_input=json.dumps(node19_input, ensure_ascii=False),
    )
    output = await generate_structured(
        SectionGenerationOutput,
        [{"role": "system", "content": system}],
        stage="generate_sections",
        temperature=0.4,
        max_tokens=8000,
    )
    return put_artifact("sections", [s.model_dump(by_alias=True) for s in output.sections])


async def _edit_one(section: dict[str, Any], plan_by_name: dict[str, Any]) -> dict[str, Any]:
    plan = plan_by_name.get(section["sectionName"], {})
    payload = {
        **section,
        "wordTarget": plan.get("wordTarget"),
        "toleranceBand": plan.get("toleranceBand"),
    }
    edited = None
    for _attempt in range(2):  # EDITORIAL, then n8n's EDITORIAL3 retry-on-empty
        system = render_prompt(
            "report_render.editorial", section_json=json.dumps(payload, ensure_ascii=False)
        )
        edited = await generate_structured(
            RenderedSection,
            [{"role": "system", "content": system}],
            stage="edit_sections",
            temperature=0.3,
        )
        word_count = len((edited.content or "").split())
        if edited.section_name and edited.content and word_count >= 100:
            break
    assert edited is not None
    return edited.model_dump(by_alias=True)


@stage_node("edit_sections")
async def edit_sections(state: PipelineState) -> dict[str, Any]:
    render_plan = state["artifacts"]["renderPlan"]
    plan_by_name = {s["sectionName"]: s for s in render_plan["sections"]}
    sections = state["artifacts"]["sections"]
    edited = await asyncio.gather(*(_edit_one(s, plan_by_name) for s in sections))
    return put_artifact("editedSections", list(edited))


def _value_appears(content: str, value: str) -> bool:
    alt1 = value.replace("-", " to ")
    alt2 = value.replace("-", " and ")
    no_commas = re.sub(r"(?<=\d),(?=\d)", "", value)
    content_norm = re.sub(r"(?<=\d),(?=\d)", "", re.sub(r"(\d+)x", r"\1", content))
    return any(v in content for v in (value, alt1, alt2)) or any(
        v in content_norm for v in (no_commas, alt1, alt2)
    )


def _mechanical_audit(
    sections: list[dict[str, Any]], render_plan: dict[str, Any], substrate: dict[str, Any]
) -> dict[str, Any]:
    """Port of n8n's "AUDIT Input" / "AUDIT Input1" Code node — deterministic, no LLM."""
    facts_map = {f["factId"]: f for f in substrate.get("facts", []) if "factId" in f}
    external_options_map = {
        e["externalOptionId"]: e
        for e in substrate.get("externalOptions", [])
        if "externalOptionId" in e
    }
    valid_citation_keys: set[str] = set()
    sources = (substrate.get("citations") or {}).get("sources")
    if sources:
        for c in sources:
            key = c.get("sourceId") or c.get("key") or c.get("citationKey")
            if key:
                valid_citation_keys.add(key)
    else:
        for arr in (
            substrate.get("facts", []),
            substrate.get("settledRecommendations", []),
            substrate.get("externalOptions", []),
        ):
            for item in arr or []:
                valid_citation_keys.update(item.get("citationKeys", []) or [])

    rendered_names = {s["sectionName"] for s in sections}
    defects: list[dict[str, str]] = []

    for rsec in render_plan.get("sections", []):
        if rsec["sectionName"] not in rendered_names:
            defects.append(
                {
                    "sectionName": rsec["sectionName"],
                    "defectType": "missing_section",
                    "detail": f'Required section "{rsec["sectionName"]}" is absent from generated '
                    "output",
                }
            )

    for section in sections:
        name = section["sectionName"]
        content = section.get("content") or ""

        for fact_id in section.get("factIdsUsed", []):
            fact = facts_map.get(fact_id)
            if fact is None:
                defects.append(
                    {
                        "sectionName": name,
                        "defectType": "unknown_fact_id",
                        "detail": f'factId "{fact_id}" does not exist in the facts register',
                    }
                )
                continue
            value = str(fact.get("value") or "").strip()
            if value and not _value_appears(content, value):
                defects.append(
                    {
                        "sectionName": name,
                        "defectType": "figure_mismatch",
                        "detail": f'Fact "{fact_id}" declared used but its register value '
                        f'"{value}" does not appear in the section prose',
                    }
                )

        wrong_type = [k for k in section.get("citationKeysUsed", []) if not k.startswith("S")]
        for k in wrong_type:
            defects.append(
                {
                    "sectionName": name,
                    "defectType": "wrong_key_type",
                    "detail": f'"{k}" is not a source key — fact or option IDs must not appear '
                    "in citationKeysUsed",
                }
            )
        for key in (k for k in section.get("citationKeysUsed", []) if k.startswith("S")):
            if key not in valid_citation_keys:
                defects.append(
                    {
                        "sectionName": name,
                        "defectType": "unresolved_footnote",
                        "detail": f'Citation key "{key}" does not resolve to a known source',
                    }
                )
        for opt_id in section.get("externalOptionIdsUsed", []):
            if opt_id not in external_options_map:
                defects.append(
                    {
                        "sectionName": name,
                        "defectType": "unknown_external_option",
                        "detail": f'externalOptionId "{opt_id}" does not exist in the substrate',
                    }
                )
        if section.get("unfillable") and section.get("wordCount", 0) > 50:
            defects.append(
                {
                    "sectionName": name,
                    "defectType": "unfillable_has_content",
                    "detail": f"Section marked unfillable but has {section['wordCount']} words "
                    "of content",
                }
            )
        if not section.get("unfillable") and not content.strip():
            defects.append(
                {
                    "sectionName": name,
                    "defectType": "empty_section",
                    "detail": "Section is empty but not marked unfillable",
                }
            )

    return {"passed": not defects, "mechanicalDefects": defects, "defectCount": len(defects)}


@stage_node("run_mechanical_audit")
async def run_mechanical_audit(state: PipelineState) -> dict[str, Any]:
    req = get_request(state, RenderRequest)
    audit = _mechanical_audit(
        state["artifacts"]["editedSections"], state["artifacts"]["renderPlan"], req.substrate
    )
    return put_artifact("mechanicalAudit", audit)


def _consolidate_findings_1(critic_outputs: list[dict[str, Any]]) -> dict[str, Any]:
    """Port of n8n node "Consolidate Findings 1"."""
    all_findings: list[dict[str, Any]] = []
    for out in critic_outputs:
        critic = out.get("critic")
        if critic in (
            "traceability_auditor",
            "coherence_checker",
            "red_team",
            "render_conformance",
        ):
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
    req = get_request(state, RenderRequest)
    sections = state["artifacts"]["editedSections"]
    render_plan = state["artifacts"]["renderPlan"]
    mechanical = state["artifacts"]["mechanicalAudit"]
    extracts = _substrate_extracts(req.substrate)
    engagement_inputs = {"project": req.project.model_dump(by_alias=True)}

    qc1, qc2, qc3, qc4, qc5, qc_c1 = await asyncio.gather(
        _critic(
            "report_render.qc1_traceability",
            QC1Output,
            "qc1_input",
            {
                "reportSections": sections,
                "substrateExtracts": extracts,
                "engagementInputs": engagement_inputs,
                "mechanicalDefects": mechanical["mechanicalDefects"],
            },
            "qc1",
        ),
        _critic(
            "report_render.qc2_coherence",
            QC2Output,
            "qc2_input",
            {"reportSections": sections, "renderPlan": render_plan, "substrateExtracts": extracts},
            "qc2",
        ),
        _critic(
            "report_render.qc3_reader_panel",
            QC3Output,
            "qc3_input",
            {
                "reportSections": sections,
                "engagementInputs": engagement_inputs,
                "agentProfile": {
                    "primaryReader": render_plan.get("primaryReader"),
                    "intendedUse": render_plan.get("intendedUse"),
                    "stakeholderLensMap": extracts.get("stakeholderLensMap"),
                },
            },
            "qc3",
        ),
        _critic(
            "report_render.qc4_red_team",
            QC4Output,
            "qc4_input",
            {
                "reportSections": sections,
                "substrateExtracts": extracts,
                "engagementInputs": engagement_inputs,
            },
            "qc4",
        ),
        _critic(
            "report_render.qc5_genericity",
            QC5Output,
            "qc5_input",
            {
                "reportSections": sections,
                "renderPlan": render_plan,
                "engagementInputs": engagement_inputs,
            },
            "qc5",
        ),
        _critic(
            "report_render.qc_c1_conformance",
            QCC1Output,
            "qc_c1_input",
            {"reportSections": sections, "renderPlan": render_plan, "substrateExtracts": extracts},
            "qc_c1",
        ),
    )
    critic_outputs = [o.model_dump(by_alias=True) for o in (qc1, qc2, qc3, qc4, qc5, qc_c1)]
    consolidated = _consolidate_findings_1(critic_outputs)
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
    qc6_input = {
        "reportSections": state["artifacts"]["editedSections"],
        "renderPlan": state["artifacts"]["renderPlan"],
        "consolidatedFindings": first_pass["consolidatedFindings"],
        "criticOutputs": first_pass["criticOutputs"],
        "protectionList": first_pass["protectionList"],
    }
    output = await _critic(
        "report_render.qc6_revision", QC6Output, "qc6_input", qc6_input, "revise_report"
    )
    return put_artifact("revision", output.model_dump(by_alias=True))


@stage_node("recheck_qc")
async def recheck_qc(state: PipelineState) -> dict[str, Any]:
    req = get_request(state, RenderRequest)
    render_plan = state["artifacts"]["renderPlan"]
    revised_sections = state["artifacts"]["revision"]["revisedSections"]
    extracts = _substrate_extracts(req.substrate)
    mechanical = _mechanical_audit(revised_sections, render_plan, req.substrate)

    qc1, qc2, qc_c1 = await asyncio.gather(
        _critic(
            "report_render.qc1_traceability",
            QC1Output,
            "qc1_input",
            {
                "reportSections": revised_sections,
                "substrateExtracts": extracts,
                "engagementInputs": {"project": req.project.model_dump(by_alias=True)},
                "mechanicalDefects": mechanical["mechanicalDefects"],
            },
            "qc1_recheck",
        ),
        _critic(
            "report_render.qc2_coherence",
            QC2Output,
            "qc2_input",
            {
                "reportSections": revised_sections,
                "renderPlan": render_plan,
                "substrateExtracts": extracts,
            },
            "qc2_recheck",
        ),
        _critic(
            "report_render.qc_c1_conformance",
            QCC1Output,
            "qc_c1_input",
            {
                "reportSections": revised_sections,
                "renderPlan": render_plan,
                "substrateExtracts": extracts,
            },
            "qc_c1_recheck",
        ),
    )
    recheck_outputs = [o.model_dump(by_alias=True) for o in (qc1, qc2, qc_c1)]
    first_pass = state["artifacts"]["qcFirstPass"]
    original_qc345 = [
        o
        for o in first_pass["criticOutputs"]
        if o.get("critic") in ("reader_persona_panel", "red_team", "surprise_genericity_scorer")
    ]
    consolidated = {"criticOutputs": [*recheck_outputs, *original_qc345], "cycleCount": 1}
    return {"artifacts": {"mechanicalAuditFinal": mechanical, "qcConsolidated": consolidated}}


@stage_node("finalize_first_pass")
async def finalize_first_pass(state: PipelineState) -> dict[str, Any]:
    first_pass = state["artifacts"]["qcFirstPass"]
    return {
        "artifacts": {
            "qcConsolidated": {"criticOutputs": first_pass["criticOutputs"], "cycleCount": 0}
        }
    }


@stage_node("score_and_gate")
async def score_and_gate(state: PipelineState) -> dict[str, Any]:
    req = get_request(state, RenderRequest)
    render_plan = state["artifacts"]["renderPlan"]
    qc_consolidated = state["artifacts"]["qcConsolidated"]
    revision = state["artifacts"].get("revision")
    final_sections = (
        revision["revisedSections"] if revision else state["artifacts"]["editedSections"]
    )

    substrate_availability = {
        "preferredFuture": bool(req.substrate.get("preferredFuture")),
        "investmentEnvelopes": bool(req.substrate.get("investmentEnvelopes")),
        "provocations": bool(req.substrate.get("provocations")),
    }
    section_completeness = [
        {
            "sectionName": s["sectionName"],
            "unfillable": s.get("unfillable", False),
            "wordCount": s.get("wordCount", 0),
        }
        for s in final_sections
    ]
    qc7_input = {
        "criticOutputs": qc_consolidated["criticOutputs"],
        "revisionLog": {"change_log": revision["changeLog"], "unresolved": revision["unresolved"]}
        if revision
        else {"change_log": [], "unresolved": []},
        "cycleCount": qc_consolidated["cycleCount"],
        "renderPlan": render_plan,
        "sectionCompleteness": section_completeness,
        "substrateAvailability": substrate_availability,
    }
    output = await _critic(
        "report_render.qc7_scorecard", QC7Output, "qc7_input", qc7_input, "score_and_gate"
    )
    return put_artifact("scorecard", output.model_dump(by_alias=True))


def _assemble_report_markdown(
    sections: list[dict[str, Any]], sources_map: dict[str, dict[str, Any]]
) -> tuple[str, list[str]]:
    """Port of n8n node "Code in JavaScript9" (final assembly)."""
    footnote_order: list[str] = []
    footnote_map: dict[str, int] = {}
    for section in sections:
        for key in section.get("citationKeysUsed", []):
            if key.startswith("S") and key not in footnote_map:
                footnote_order.append(key)
                footnote_map[key] = len(footnote_order)

    citation_re = re.compile(r"\(([^)]+)\)")

    def _replace_citations(m: re.Match[str]) -> str:
        keys = [k.strip() for k in m.group(1).split(",") if k.strip().startswith("S")]
        nums = [footnote_map[k] for k in keys if k in footnote_map]
        return "".join(f"[{n}]" for n in nums) if nums else m.group(0)

    lines: list[str] = [""]
    for section in sections:
        if section.get("unfillable"):
            continue
        lines.append(f"## {section['sectionName']}")
        lines.append("")
        prose = section.get("content") or ""
        prose = citation_re.sub(_replace_citations, prose)
        prose = re.sub(r"\[F\d+\]", "", prose)
        prose = re.sub(r"\(\s*[,;\s]*\)", "", prose)
        prose = re.sub(r"\s+([.,;:])", r"\1", prose)
        prose = re.sub(r"[ \t]{2,}", " ", prose)
        lines.append(prose)
        lines.append("")

    if footnote_order:
        lines += ["---", "", "## References", ""]
        for key in footnote_order:
            num = footnote_map[key]
            source = sources_map.get(key, {})
            text = source.get("footnoteText") or source.get("title") or key
            url = source.get("url")
            suffix = f"  {url}" if url and url not in text else ""
            lines.append(f"{num}. {text}{suffix}")
        lines.append("")

    return "\n".join(lines), footnote_order


@stage_node("assemble_callback")
async def assemble_callback(state: PipelineState) -> dict[str, Any]:
    req = get_request(state, RenderRequest)
    archetype = _archetype(req)
    revision = state["artifacts"].get("revision")
    sections = revision["revisedSections"] if revision else state["artifacts"]["editedSections"]
    mechanical = (
        state["artifacts"].get("mechanicalAuditFinal") or state["artifacts"]["mechanicalAudit"]
    )
    scorecard = state["artifacts"]["scorecard"]

    sources = (req.substrate.get("citations") or {}).get("sources", [])
    sources_map = {s["sourceId"]: s for s in sources if s.get("sourceId")}
    content, footnote_order = _assemble_report_markdown(sections, sources_map)

    fillable = [s for s in sections if not s.get("unfillable")]
    total_words = sum(s.get("wordCount", 0) for s in fillable)
    template = archetype["definition"].get("template", "Report")
    words_per_page = _WORDS_PER_PAGE.get(template, 400)
    page_estimate = round((total_words / words_per_page) * 10) / 10 if words_per_page else 0.0

    gate = scorecard.get("gate")
    status = (
        "failed" if not mechanical.get("passed") else "partial" if gate == "HOLD" else "completed"
    )

    report = {
        "archetypeKey": archetype["key"],
        "archetypeName": archetype["definition"].get("name", archetype["key"]),
        "content": content,
        "wordCount": total_words,
        "pageEstimate": page_estimate,
        "citationCount": len(footnote_order),
        "auditPassed": mechanical.get("passed"),
        "auditFlags": [
            {"section": d["sectionName"], "type": d["defectType"], "detail": d["detail"]}
            for d in mechanical.get("mechanicalDefects", [])
        ],
        "qcGate": gate,
        "qcScorecard": scorecard.get("scorecardMarkdown"),
        "qcOpenFindings": scorecard.get("openFindings"),
    }
    callback = RenderCallback(
        render_batch_id=req.render_batch_id or req.session_id,
        project_id=req.project.project_id,
        status=status,
        reports=[report],
        execution_id=state["run_id"],
    )
    return put_result(callback)


def build() -> StateGraph:
    g: StateGraph = StateGraph(PipelineState)
    g.add_node("detect_gaps", detect_gaps)
    g.add_node("search_external", search_external)
    g.add_node("plan_render", plan_render)
    g.add_node("plan_fact_currency", plan_fact_currency)
    g.add_node("generate_sections", generate_sections)
    g.add_node("edit_sections", edit_sections)
    g.add_node("run_mechanical_audit", run_mechanical_audit)
    g.add_node("run_qc_panel", run_qc_panel)
    g.add_node("revise_report", revise_report)
    g.add_node("recheck_qc", recheck_qc)
    g.add_node("finalize_first_pass", finalize_first_pass)
    g.add_node("score_and_gate", score_and_gate)
    g.add_node("assemble_callback", assemble_callback)

    g.add_edge(START, "detect_gaps")
    g.add_edge("detect_gaps", "search_external")
    g.add_edge("search_external", "plan_render")
    g.add_edge("plan_render", "plan_fact_currency")
    g.add_edge("plan_fact_currency", "generate_sections")
    g.add_edge("generate_sections", "edit_sections")
    g.add_edge("edit_sections", "run_mechanical_audit")
    g.add_edge("run_mechanical_audit", "run_qc_panel")
    g.add_conditional_edges(
        "run_qc_panel", fan_out_revision, ["revise_report", "finalize_first_pass"]
    )
    g.add_edge("revise_report", "recheck_qc")
    g.add_edge("recheck_qc", "score_and_gate")
    g.add_edge("finalize_first_pass", "score_and_gate")
    g.add_edge("score_and_gate", "assemble_callback")
    g.add_edge("assemble_callback", END)
    return g
