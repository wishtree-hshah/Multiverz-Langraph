"""capstone_substrate workflow.

n8n source: "Strategy Navigator Capstone Pipeline (4).json" (78 nodes). Traced
node-by-node from the export's actual Code nodes and connections — the
deterministic Code nodes here carry as much load-bearing logic as the 13 LLM
calls, and several output contracts (e.g. the entity-consolidation "decisions"
wrapper keys) were only recoverable from the Code node that consumes them, not
from the prompt text. See docs/MIGRATION-FROM-N8N.md.

Graph (semantic dependency order — LangGraph node granularity groups several
n8n nodes that only depend on the raw payload, since n8n's own Merge/Aggregate
choreography is an artifact of its execution model, not part of the port
contract):

    resolve_citations -> build_foundation -> bind_and_cluster
        -> consolidate_recommendations -> lens_and_enrich
        -> future_and_investment -> assemble_substrate
        -> review_and_finalize

Traced control flow and business logic (n8n node names in the export):

* **"Code in JavaScript2"** — deterministic URL-dedup pre-pass. Parses every
  `solutionReferences` block (step-level and object-level) plus ideation
  `sources[]` into fragments, normalises and dedupes URLs into a `sources`
  table, and collects everything else as `proseResidual`. Node 2 (an LLM
  call) resolves only the leftover prose. **"Code in JavaScript3"** then
  folds Node 2's `additions` back into the deduped table.
* **"Entity Consolidation Input"** builds the *full* per-type entry
  (`originalId`, `agentId`, `title`, `domain`, `tags`, numeric fields,
  `description`, `implications`, `location`) for signals/uncertainties/best
  practices; the prompt's own template then sends the LLM a *slimmed* view
  (drops `tags`/`location`, truncates long text) — ported as
  `_slim_for_entity_prompt`. **"Code in JavaScript1"** assigns scenario ids
  deterministically (no LLM). **"Code in JavaScript"** (after all four
  branches merge) reconstructs final consolidated items from the LLM's
  `sigDecisions`/`uncDecisions`/`bpDecisions` — unioning `tags`,
  `sourceAgents`, `sourceLocations` across each group's members and building
  the `idMap` (`originalId` -> `substrateId`). Ported verbatim as
  `_reconstruct_entities`.
* **"(Node 8) Divergence"** and **"(Node 10) Trend Prioritization
  Enrichment"** are deterministic Code nodes, no LLM — ported verbatim as
  `_compute_divergence` / `_enrich_trends`.
* **"Investment Sizing Rollup"** is deterministic: assigns `investmentId`,
  forces `indicative: true`, swaps any inverted low/high range, and computes
  `investmentSummary` totals (sum of *low*/*high* across covered
  recommendations) — the LLM never computes a total. Ported verbatim as
  `_rollup_investment`.
* **"(Node 11) Substrate Assembly and Validation"** is the frozen-substrate
  assembler — deterministic, no LLM. It repairs facts that came back
  `uncited: true` from Node 3 (which, verified against "Facts Register
  Input", never actually receives a source table) by matching numbers
  (>=10, to avoid false positives) between a fact's statement and the
  signals/uncertainties/best-practices text whose `sourceLocations` are
  known, then attaching those sources. It also relocates misplaced
  `SIG###`/`BP###` ids out of `settledRecommendations[].citationKeys` into
  their proper arrays. Ported verbatim as `_assemble_substrate`.
* Two **deliberate corrections** over what the exported graph actually
  wires, both informational-only (no control-flow risk): (1) Node 11
  computes real `violations` for the citationKey-relocation logic but the
  export never returns them to "Substrate Review Input", which reads
  `raw.violations || []` — always empty in production. This port surfaces
  the real violations, matching what node 11b's own prompt says it expects.
  (2) `(Node 11b) Substrate Review`'s verdict is computed but "Edit Fields5"
  (the final callback body) never actually includes it, despite the
  prompt's own note that "the verdict travels with the substrate... on the
  callback". This port attaches it as `substrate["review"]`.
* **Node 7c (Investment Sizing)** and the citation-resolution **Node 2**
  both have a web-search tool attached in n8n; ported using
  `tools.search.jina_search` (already Postgres-cached) composed into the
  prompt, same pattern as report_render's external-search node — Node 2
  itself has no search tool (it resolves prose citations from what it's
  given), only Node 7c does.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any
from urllib.parse import urlsplit

from langgraph.graph import END, START, StateGraph

from strategy_navigator.graph.state import PipelineState
from strategy_navigator.llm.structured import generate_structured
from strategy_navigator.logging import get_logger
from strategy_navigator.prompts import render_prompt
from strategy_navigator.schemas.capstone import SubstrateCallback, SubstrateRequest
from strategy_navigator.schemas.capstone_substrate import (
    BpDecisionsOutput,
    CitationResolutionOutput,
    FactsRegisterOutput,
    ForesightActionMapOutput,
    InvestmentSizingOutput,
    PreferredFutureOutput,
    RecommendationConsolidationOutput,
    RelationalBindingOutput,
    SigDecisionsOutput,
    StakeholderLensingOutput,
    SubstrateReviewOutput,
    TrendClusteringOutput,
    UncDecisionsOutput,
)
from strategy_navigator.stages.base import get_request, put_artifact, put_result, stage_node
from strategy_navigator.tools.search import jina_search

log = get_logger(__name__)


async def _call(ref: str, schema: type, var_name: str, payload: Any, stage: str, **kw: Any) -> Any:
    system = render_prompt(ref, **{var_name: json.dumps(payload, ensure_ascii=False)})
    return await generate_structured(
        schema, [{"role": "system", "content": system}], stage=stage, **kw
    )


def _is_signal(ws: dict[str, Any]) -> bool:
    return "weak" in str(ws.get("type") or "").lower()


def _loc(agent_id: Any, obj: str, obj_id: Any, field: str) -> str:
    if obj_id is None:
        return f"agent:{agent_id}|{obj}|{field}"
    return f"agent:{agent_id}|{obj}:{obj_id}|{field}"


# =====================================================================
# resolve_citations — Node 2 + "Code in JavaScript2/3"
# =====================================================================


def _extract_fragments(
    ten_step_input: dict[str, Any], ideas_input: dict[str, Any]
) -> list[dict[str, Any]]:
    """Port of "Citation Resolution Input"."""
    fragments: list[dict[str, Any]] = []
    seq = 1

    def next_id() -> str:
        nonlocal seq
        fid = f"frag-{seq:04d}"
        seq += 1
        return fid

    def make_fragment(agent_id: Any, location: str, sr: Any) -> dict[str, Any] | None:
        if not isinstance(sr, dict):
            return None
        citations_text = sr.get("citations") or ""
        reference_urls = sr.get("referenceUrls") or []
        reference_docs = sr.get("referenceDocuments") or []
        if not citations_text and not reference_urls and not reference_docs:
            return None
        return {
            "fragmentId": next_id(),
            "origin": "tenstep",
            "location": location,
            "citationsText": citations_text,
            "referenceUrls": reference_urls,
            "referenceDocuments": reference_docs,
            "sourceStrings": [],
        }

    for sol in ten_step_input.get("solutions", []):
        agent_id = (sol.get("agentInfo") or {}).get("agentId")
        form = sol.get("10StepForm")
        if not form:
            continue
        for step in range(2, 10):
            key = f"step{step}SolutionReferences"
            frag = make_fragment(agent_id, f"agent:{agent_id}|{key}", form.get(key))
            if frag:
                fragments.append(frag)
        for ws in form.get("weakSignals") or []:
            frag = make_fragment(
                agent_id,
                f"agent:{agent_id}|weakSignals:{ws.get('id')}|solutionReferences",
                ws.get("solutionReferences"),
            )
            if frag:
                fragments.append(frag)
        for bp in form.get("bestPractices") or []:
            frag = make_fragment(
                agent_id,
                f"agent:{agent_id}|bestPractices:{bp.get('id')}|solutionReferences",
                bp.get("solutionReferences"),
            )
            if frag:
                fragments.append(frag)
        for i, sf in enumerate(form.get("solutionFrameworks") or []):
            frag = make_fragment(
                agent_id,
                f"agent:{agent_id}|solutionFrameworks:{i}|solutionReferences",
                sf.get("solutionReferences"),
            )
            if frag:
                fragments.append(frag)

    for idea in ideas_input.get("projectIdeas") or []:
        if idea.get("sources"):
            fragments.append(
                {
                    "fragmentId": next_id(),
                    "origin": "ideation",
                    "location": f"ideation|projectIdea:{idea.get('id')}|sources",
                    "citationsText": "",
                    "referenceUrls": [],
                    "referenceDocuments": [],
                    "sourceStrings": idea["sources"],
                }
            )
    for sol in ideas_input.get("solutions") or []:
        agent_id = (sol.get("agentInfo") or {}).get("agentId")
        for idea in sol.get("solutionIdeas") or []:
            if idea.get("sources"):
                fragments.append(
                    {
                        "fragmentId": next_id(),
                        "origin": "ideation",
                        "location": f"agent:{agent_id}|solutionIdea:{idea.get('id')}|sources",
                        "citationsText": "",
                        "referenceUrls": [],
                        "referenceDocuments": [],
                        "sourceStrings": idea["sources"],
                    }
                )
    return fragments


def _norm_url(u: str | None) -> str | None:
    if not u or not isinstance(u, str) or not re.match(r"^https?://", u.strip(), re.I):
        return None
    s = re.sub(r"#.*$", "", u.strip())
    try:
        parts = urlsplit(s)
        host = re.sub(r"^www\.", "", parts.netloc, flags=re.I).lower()
        path = re.sub(r"/+$", "", parts.path)
        query = f"?{parts.query}" if parts.query else ""
        return f"{host}{path}{query}"
    except Exception:
        return re.sub(r"/+$", "", s).lower()


def _parse_markdown_citations(text: str) -> list[dict[str, str | None]]:
    if not text:
        return []
    items = re.split(r"\n(?=\s*\d+\.\s)", text)
    link_re = re.compile(r"\[\*?\s*([^\]]*?)\s*\*?\]\((https?://[^)\s]+)\)")
    out: list[dict[str, str | None]] = []
    for c in [t.strip() for t in items if t.strip()] or [text]:
        m = link_re.search(c)
        if not m:
            continue
        before = re.sub(r"^\s*\d+\.\s*", "", c[: m.start()]).strip(" .")
        after = c[m.end() :].strip(" .")
        out.append(
            {
                "publisher": before or None,
                "title": m.group(1).strip() or None,
                "date": after or None,
                "url": m.group(2).strip(),
            }
        )
    return out


def _compose_footnote(
    publisher: str | None, title: str | None, date: str | None, url: str | None
) -> str:
    line = ", ".join(x for x in (publisher, f'"{title}"' if title else None) if x)
    if date:
        line = f"{line}. {date}." if line else f"{date}."
    if url:
        line = f"{line} {url}" if line else url
    return line or url or ""


def _dedup_citations(fragments: list[dict[str, Any]]) -> dict[str, Any]:
    """Port of "Code in JavaScript2" — deterministic citation dedup."""
    meta_by_url: dict[str, dict[str, Any]] = {}
    for f in fragments:
        for md in _parse_markdown_citations(f.get("citationsText", "")):
            key = _norm_url(md.get("url"))
            if not key:
                continue
            score = sum(1 for k in ("publisher", "title", "date") if md.get(k))
            if key not in meta_by_url or score > meta_by_url[key]["_score"]:
                meta_by_url[key] = {**md, "_score": score}

    by_url: dict[str, dict[str, Any]] = {}
    prose_residual: list[dict[str, Any]] = []

    def add_url(raw: str, origin: str, frag_id: str, location: str) -> bool:
        key = _norm_url(raw)
        if not key:
            return False
        a = by_url.setdefault(
            key, {"url": raw.strip(), "origins": set(), "frags": set(), "locs": set()}
        )
        a["origins"].add(origin)
        a["frags"].add(frag_id)
        a["locs"].add(location)
        return True

    for f in fragments:
        frag_id, location, origin = f["fragmentId"], f["location"], f["origin"]
        for u in f.get("referenceUrls") or []:
            add_url(u, origin, frag_id, location)
        for s in f.get("sourceStrings") or []:
            if not add_url(s, origin, frag_id, location) and s and s.strip():
                prose_residual.append(
                    {
                        "text": s.strip(),
                        "origin": origin,
                        "fragmentId": frag_id,
                        "location": location,
                    }
                )
        for d in f.get("referenceDocuments") or []:
            if str(d or "").strip():
                prose_residual.append(
                    {
                        "text": str(d).strip(),
                        "origin": origin,
                        "fragmentId": frag_id,
                        "location": location,
                    }
                )
        has_links = bool(re.search(r"\]\(https?://", f.get("citationsText") or ""))
        if f.get("citationsText") and not has_links:
            prose_residual.append(
                {
                    "text": f["citationsText"].strip(),
                    "origin": origin,
                    "fragmentId": frag_id,
                    "location": location,
                }
            )

    sources = []
    for i, a in enumerate(by_url.values(), start=1):
        norm = _norm_url(a["url"])
        meta = meta_by_url.get(norm) if norm else None
        footnote = (
            _compose_footnote(meta["publisher"], meta["title"], meta["date"], a["url"])
            if meta
            else a["url"]
        )
        sources.append(
            {
                "sourceId": f"S{i:03d}",
                "footnoteText": footnote,
                "url": a["url"],
                "origin": "tenstep" if "tenstep" in a["origins"] else "ideation",
                "contributingFragments": list(a["frags"]),
                "contributingLocations": list(a["locs"]),
            }
        )
    return {"sources": sources, "proseResidual": prose_residual}


def _apply_citation_additions(
    sources: list[dict[str, Any]], additions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Port of "Code in JavaScript3"."""
    by_id = {
        s["sourceId"]: {
            **s,
            "contributingFragments": list(s["contributingFragments"]),
            "contributingLocations": list(s["contributingLocations"]),
        }
        for s in sources
    }
    new_ones: list[dict[str, Any]] = []
    for a in additions:
        matches = a.get("matchesExistingId")
        if matches and matches in by_id:
            t = by_id[matches]
            t["contributingFragments"] = list(
                dict.fromkeys([*t["contributingFragments"], *a.get("contributingFragments", [])])
            )
            t["contributingLocations"] = list(
                dict.fromkeys([*t["contributingLocations"], *a.get("contributingLocations", [])])
            )
        else:
            new_ones.append(
                {
                    "footnoteText": a.get("footnoteText", ""),
                    "url": None,
                    "origin": a.get("origin") or "ideation",
                    "contributingFragments": a.get("contributingFragments", []),
                    "contributingLocations": a.get("contributingLocations", []),
                }
            )
    final = list(by_id.values()) + new_ones
    return [{**s, "sourceId": f"S{i:03d}"} for i, s in enumerate(final, start=1)]


@stage_node("resolve_citations")
async def resolve_citations(state: PipelineState) -> dict[str, Any]:
    req = get_request(state, SubstrateRequest)
    fragments = _extract_fragments(req.ten_step_input, req.ideas_input)
    deduped = _dedup_citations(fragments)
    sources, prose_residual = deduped["sources"], deduped["proseResidual"]

    if not prose_residual:
        return put_artifact("sources", sources)

    system = render_prompt(
        "capstone_substrate.citation_resolution",
        sources_json=json.dumps(
            [{"sourceId": s["sourceId"], "footnoteText": s["footnoteText"]} for s in sources]
        ),
        prose_residual_json=json.dumps(
            [{"fragmentId": p["fragmentId"], "text": p["text"]} for p in prose_residual]
        ),
    )
    output = await generate_structured(
        CitationResolutionOutput, [{"role": "system", "content": system}], stage="resolve_citations"
    )
    final_sources = _apply_citation_additions(
        sources, [a.model_dump(by_alias=True) for a in output.additions]
    )
    return put_artifact("sources", final_sources)


# =====================================================================
# build_foundation — Node 3, Node 4a (x3 + scenarios), Node 6, Node 8
# =====================================================================


def _build_agent_content(ten_step_input: dict[str, Any]) -> list[dict[str, Any]]:
    """Port of "Facts Register Input"."""
    narrative_fields = [
        "driversOfChange",
        "keyInsights",
        "opportunitySpaces",
        "riskResilience",
        "innovationPathways",
        "quickLongTermStrategies",
        "solutionExplorationInnovation",
        "solutionImplementation",
        "problemChallengeSynthesis",
        "executiveSummary",
        "nextPractices",
    ]
    step10_fields = [
        "key_figures",
        "executive_summary",
        "stakeholder_context",
        "signals_and_drivers_relevant_to_this_stakeholder",
        "critical_uncertainties_through_this_stakeholders_lens",
        "strategic_scenarios_stakeholder_specific_reading",
        "implications_across_three_horizons",
        "strategic_options_and_robustness",
        "indicators_to_monitor",
        "action_pathways",
    ]

    def tagged(text: Any, location: str) -> dict[str, Any]:
        return {"text": text or "", "location": location}

    agent_content = []
    for sol in ten_step_input.get("solutions", []):
        agent_id = (sol.get("agentInfo") or {}).get("agentId")
        form = sol.get("10StepForm") or {}
        signals: list[dict[str, Any]] = []
        uncertainties: list[dict[str, Any]] = []
        for ws in form.get("weakSignals") or []:
            entry = {
                "id": ws.get("id"),
                "title": ws.get("title"),
                "type": ws.get("type"),
                "domain": ws.get("domain"),
                "impact": ws.get("impact"),
                "uncertainty": ws.get("uncertainty"),
                "probability": ws.get("probability"),
                "horizon": ws.get("timeRange"),
                "relatedWeakSignals": ws.get("relatedWeakSignals") or "",
                "description": tagged(
                    ws.get("description"),
                    _loc(agent_id, "weakSignals", ws.get("id"), "description"),
                ),
                "implications": tagged(
                    ws.get("implications"),
                    _loc(agent_id, "weakSignals", ws.get("id"), "implications"),
                ),
                "evidenceOrEarlySignal": tagged(
                    ws.get("evidenceOrEarlySignal"),
                    _loc(agent_id, "weakSignals", ws.get("id"), "evidenceOrEarlySignal"),
                ),
            }
            (signals if _is_signal(ws) else uncertainties).append(entry)

        best_practices = [
            {
                "id": bp.get("id"),
                "title": bp.get("title"),
                "organizationName": bp.get("organizationName"),
                "tags": bp.get("tags") or [],
                "challenge": tagged(
                    bp.get("challenge"), _loc(agent_id, "bestPractices", bp.get("id"), "challenge")
                ),
                "solutionText": tagged(
                    bp.get("solutionText"),
                    _loc(agent_id, "bestPractices", bp.get("id"), "solutionText"),
                ),
                "outcome": tagged(
                    bp.get("outcome"), _loc(agent_id, "bestPractices", bp.get("id"), "outcome")
                ),
                "implementation": tagged(
                    bp.get("implementation"),
                    _loc(agent_id, "bestPractices", bp.get("id"), "implementation"),
                ),
            }
            for bp in form.get("bestPractices") or []
        ]
        scenarios = [
            {
                "index": i,
                "type": sf.get("type"),
                "axes": sf.get("axes") or {},
                "weakSignal1": sf.get("weakSignal1") or "",
                "weakSignal2": sf.get("weakSignal2") or "",
                "scenarioA": tagged(
                    sf.get("scenarioA"), _loc(agent_id, "solutionFrameworks", i, "scenarioA")
                ),
                "scenarioB": tagged(
                    sf.get("scenarioB"), _loc(agent_id, "solutionFrameworks", i, "scenarioB")
                ),
                "scenarioC": tagged(
                    sf.get("scenarioC"), _loc(agent_id, "solutionFrameworks", i, "scenarioC")
                ),
                "scenarioD": tagged(
                    sf.get("scenarioD"), _loc(agent_id, "solutionFrameworks", i, "scenarioD")
                ),
                "scenarioAnalysisKeyInsight": tagged(
                    sf.get("scenarioAnalysisKeyInsight"),
                    _loc(agent_id, "solutionFrameworks", i, "scenarioAnalysisKeyInsight"),
                ),
            }
            for i, sf in enumerate(form.get("solutionFrameworks") or [])
        ]
        narratives = {
            f: tagged(form[f], _loc(agent_id, "narratives", None, f))
            for f in narrative_fields
            if form.get(f)
        }
        opportunity_tree = [
            {**op, "location": _loc(agent_id, "solutionOpportunities", i, "idea")}
            for i, op in enumerate(form.get("solutionOpportunities") or [])
        ]
        s10 = form.get("step10") or {}
        step10 = {
            f: tagged(s10[f], _loc(agent_id, "step10", None, f))
            for f in step10_fields
            if s10.get(f)
        }

        agent_content.append(
            {
                "agentId": agent_id,
                "signals": signals,
                "uncertainties": uncertainties,
                "bestPractices": best_practices,
                "scenarios": scenarios,
                "narratives": narratives,
                "opportunityTree": opportunity_tree,
                "step10": step10,
            }
        )
    return agent_content


def _build_entity_input(ten_step_input: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Port of "Entity Consolidation Input" — full (unslimmed) entries."""
    signals: list[dict[str, Any]] = []
    uncertainties: list[dict[str, Any]] = []
    best_practices: list[dict[str, Any]] = []
    scenarios: list[dict[str, Any]] = []
    for sol in ten_step_input.get("solutions", []):
        agent_id = (sol.get("agentInfo") or {}).get("agentId")
        form = sol.get("10StepForm") or {}
        for ws in form.get("weakSignals") or []:
            entry = {
                "agentId": agent_id,
                "originalId": ws.get("id"),
                "title": ws.get("title") or "",
                "domain": ws.get("domain") or "",
                "tags": ws.get("tags") or [],
                "impact": ws.get("impact") or 0,
                "uncertainty": ws.get("uncertainty") or 0,
                "probability": float(ws.get("probability") or 0),
                "horizon": ws.get("timeRange") or "",
                "description": ws.get("description") or "",
                "implications": ws.get("implications") or "",
                "location": _loc(agent_id, "weakSignals", ws.get("id"), "description"),
            }
            (signals if _is_signal(ws) else uncertainties).append(entry)
        for bp in form.get("bestPractices") or []:
            best_practices.append(
                {
                    "agentId": agent_id,
                    "originalId": bp.get("id"),
                    "title": bp.get("title") or "",
                    "organizationName": bp.get("organizationName") or "",
                    "challenge": bp.get("challenge") or "",
                    "solutionText": bp.get("solutionText") or "",
                    "outcome": bp.get("outcome") or "",
                    "implementation": bp.get("implementation") or "",
                    "tags": bp.get("tags") or [],
                    "location": _loc(agent_id, "bestPractices", bp.get("id"), "outcome"),
                }
            )
        for i, sf in enumerate(form.get("solutionFrameworks") or []):
            scenarios.append(
                {
                    "agentId": agent_id,
                    "originalScenarioSetId": f"agent:{agent_id}|sf:{i}",
                    "method": sf.get("type") or "",
                    "scenarioA": sf.get("scenarioA") or "",
                    "scenarioB": sf.get("scenarioB") or "",
                    "scenarioC": sf.get("scenarioC") or "",
                    "scenarioD": sf.get("scenarioD") or "",
                    "keyInsight": sf.get("scenarioAnalysisKeyInsight") or "",
                    "axesRaw": sf.get("axes") or {},
                    "location": _loc(
                        agent_id, "solutionFrameworks", i, "scenarioAnalysisKeyInsight"
                    ),
                }
            )
    return {
        "signals": signals,
        "uncertainties": uncertainties,
        "bestPractices": best_practices,
        "scenarios": scenarios,
    }


def _slim_signals_or_uncertainties(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": it["originalId"],
            "agentId": it["agentId"],
            "title": it["title"],
            "domain": it["domain"],
            "impact": it["impact"],
            "uncertainty": it["uncertainty"],
            "probability": it["probability"],
            "horizon": it["horizon"],
            "description": (it["description"] or "")[:600],
            "implications": (it["implications"] or "")[:400],
        }
        for it in items
    ]


def _slim_best_practices(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": it["originalId"],
            "agentId": it["agentId"],
            "title": it["title"],
            "challenge": (it["challenge"] or "")[:500],
            "solutionText": (it["solutionText"] or "")[:500],
            "outcome": (it["outcome"] or "")[:500],
            "implementation": (it["implementation"] or "")[:400],
        }
        for it in items
    ]


def _assign_scenario_ids(scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    """Port of "Code in JavaScript1"."""
    out, id_map = [], []
    for i, s in enumerate(scenarios, start=1):
        substrate_id = f"SCN{i:03d}"
        out.append(
            {
                "scenarioSetId": substrate_id,
                "sourceAgent": s["agentId"],
                "method": s["method"],
                "scenarioA": s["scenarioA"],
                "scenarioB": s["scenarioB"],
                "scenarioC": s["scenarioC"],
                "scenarioD": s["scenarioD"],
                "keyInsight": s["keyInsight"],
                "axesRaw": s["axesRaw"],
                "sourceLocations": [s["location"]],
            }
        )
        id_map.append(
            {
                "agentId": s["agentId"],
                "originalId": s["originalScenarioSetId"],
                "substrateId": substrate_id,
            }
        )
    return {"scenarios": out, "idMap": id_map}


def _unions(member_ids: list[Any], orig_by_id: dict[Any, dict[str, Any]]) -> dict[str, Any]:
    tags: set[str] = set()
    agents: set[Any] = set()
    locs: set[str] = set()
    for mid in member_ids or []:
        o = orig_by_id.get(mid, {})
        tags.update(o.get("tags") or [])
        if o.get("agentId") is not None:
            agents.add(o["agentId"])
        loc = o.get("location")
        if isinstance(loc, list):
            locs.update(loc)
        elif loc:
            locs.add(loc)
    return {"tags": list(tags), "sourceAgents": list(agents), "sourceLocations": list(locs)}


def _reconstruct_entities(
    signal_decisions: list[dict[str, Any]],
    unc_decisions: list[dict[str, Any]],
    bp_decisions: list[dict[str, Any]],
    orig: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Port of "Code in JavaScript" (post entity-consolidation reconstruction)."""
    sig_orig = {o["originalId"]: o for o in orig["signals"]}
    unc_orig = {o["originalId"]: o for o in orig["uncertainties"]}
    bp_orig = {o["originalId"]: o for o in orig["bestPractices"]}

    def reconstruct(
        decisions: list[dict[str, Any]], orig_by_id: dict[Any, dict[str, Any]], id_field: str
    ) -> tuple[list[dict], list[dict]]:
        items, id_map = [], []
        for dec in decisions:
            members = dec.get("memberOriginalIds", [])
            u = _unions(members, orig_by_id)
            for mid in members:
                o = orig_by_id.get(mid, {})
                id_map.append(
                    {"agentId": o.get("agentId"), "originalId": mid, "substrateId": dec[id_field]}
                )
            dpick = orig_by_id.get(dec.get("descriptionFrom"), {})
            ipick = orig_by_id.get(dec.get("implicationsFrom"), {})
            item = {
                id_field: dec[id_field],
                "title": dec.get("title") or "",
                "domain": dec.get("domain") or "",
                "tags": u["tags"],
                "impact": dec.get("impact"),
                "uncertainty": dec.get("uncertainty"),
                "probability": dec.get("probability"),
                "horizon": dec.get("horizon") or "",
                "description": dpick.get("description") or "",
                "implications": ipick.get("implications") or "",
                "sourceAgents": u["sourceAgents"],
                "sourceLocations": u["sourceLocations"],
            }
            if dec.get("variants") is not None:
                item["variants"] = dec["variants"]
            items.append(item)
        return items, id_map

    sig_items, sig_map = reconstruct(signal_decisions, sig_orig, "signalId")
    unc_items, unc_map = reconstruct(unc_decisions, unc_orig, "uncertaintyId")

    bp_items, bp_map = [], []
    for dec in bp_decisions:
        members = dec.get("memberOriginalIds", [])
        u = _unions(members, bp_orig)
        for mid in members:
            o = bp_orig.get(mid, {})
            bp_map.append(
                {
                    "agentId": o.get("agentId"),
                    "originalId": mid,
                    "substrateId": dec["bestPracticeId"],
                }
            )

        def pick(field: str, dec: dict[str, Any] = dec) -> dict[str, Any]:
            return bp_orig.get(dec.get(field), {})

        bp_items.append(
            {
                "bestPracticeId": dec["bestPracticeId"],
                "title": pick("titleFrom").get("title") or "",
                "organizationName": pick("titleFrom").get("organizationName") or "",
                "challenge": pick("challengeFrom").get("challenge") or "",
                "solutionText": pick("solutionTextFrom").get("solutionText") or "",
                "outcome": pick("outcomeFrom").get("outcome") or "",
                "implementation": pick("implementationFrom").get("implementation") or "",
                "tags": u["tags"],
                "sourceAgents": u["sourceAgents"],
                "sourceLocations": u["sourceLocations"],
            }
        )

    return {
        "signals": sig_items,
        "uncertainties": unc_items,
        "bestPractices": bp_items,
        "idMap": [*sig_map, *unc_map, *bp_map],
    }


def _build_foresight_action_map_input(
    ten_step_input: dict[str, Any], ideas_input: dict[str, Any]
) -> dict[str, Any]:
    """Port of "Foresight-to-Action Map Input"."""
    rapid_ideas = [
        {
            "ideaId": i.get("id"),
            "title": i.get("title") or "",
            "summary": i.get("summary") or "",
            "categories": i.get("categories") or [],
        }
        for i in ideas_input.get("projectIdeas") or []
    ]
    solution_ideas_by_agent: dict[Any, list[dict[str, Any]]] = {}
    for sol in ideas_input.get("solutions") or []:
        agent_id = (sol.get("agentInfo") or {}).get("agentId")
        entries = []
        for i in sol.get("solutionIdeas") or []:
            entry = {
                "ideaId": i.get("id"),
                "title": i.get("title") or "",
                "summary": i.get("summary") or "",
                "categories": i.get("categories") or [],
            }
            if i.get("templateId") is not None:
                entry["templateId"] = str(i["templateId"])
            entries.append(entry)
        solution_ideas_by_agent[agent_id] = entries

    agent_ids = [
        (s.get("agentInfo") or {}).get("agentId") for s in ideas_input.get("solutions") or []
    ]
    voted_ideas_by_agent = [
        {
            "agentId": aid,
            "rapid": rapid_ideas,
            "solutionExtracted": solution_ideas_by_agent.get(aid, []),
        }
        for aid in agent_ids
    ]

    opportunity_trees_by_agent = []
    for sol in ten_step_input.get("solutions") or []:
        agent_id = (sol.get("agentInfo") or {}).get("agentId")
        form = sol.get("10StepForm") or {}
        initiatives, seen = [], set()
        for opp in form.get("solutionOpportunities") or []:
            if not isinstance(opp, dict):
                continue
            for ta in opp.get("termActionables") or []:
                if not isinstance(ta, dict):
                    continue
                ta_title = ta.get("title") or ""
                for hi in ta.get("highImpactInitiatives") or []:
                    iid = hi.get("initiativeId")
                    if not iid or iid in seen:
                        continue
                    seen.add(iid)
                    initiatives.append(
                        {
                            "initiativeId": iid,
                            "title": ta_title,
                            "termType": hi.get("termType") or "",
                            "actionableImportance": hi.get("actionableImportance") or "",
                        }
                    )
        opportunity_trees_by_agent.append({"agentId": agent_id, "initiatives": initiatives})

    return {
        "votedIdeasByAgent": voted_ideas_by_agent,
        "opportunityTreesByAgent": opportunity_trees_by_agent,
        "solutionExtractedTrackPresent": any(v for v in solution_ideas_by_agent.values()),
    }


def _compute_divergence(ideas_input: dict[str, Any]) -> dict[str, Any]:
    """Port of "(Node 8) Divergence" — deterministic, no LLM."""

    def to_float(v: Any) -> float:
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    all_ideas = []
    for idea in ideas_input.get("projectIdeas") or []:
        all_ideas.append(
            {
                "ideaId": idea.get("id"),
                "track": "rapid",
                "agentId": None,
                "title": idea.get("title") or "",
                "humanScore": to_float(idea.get("humanScore")),
                "agentScore": to_float(idea.get("agentScore")),
                "overallScore": to_float(idea.get("overallScore")),
                "ratings": idea.get("ratings") or [],
            }
        )
    for sol in ideas_input.get("solutions") or []:
        agent_id = (sol.get("agentInfo") or {}).get("agentId")
        for idea in sol.get("solutionIdeas") or []:
            all_ideas.append(
                {
                    "ideaId": idea.get("id"),
                    "track": "solutionExtracted",
                    "agentId": agent_id,
                    "title": idea.get("title") or "",
                    "humanScore": to_float(idea.get("humanScore")),
                    "agentScore": to_float(idea.get("agentScore")),
                    "overallScore": to_float(idea.get("overallScore")),
                    "ratings": idea.get("ratings") or [],
                }
            )

    def mean(scores: list[float]) -> float | None:
        return sum(scores) / len(scores) if scores else None

    def reconciles(computed: float | None, stored: float) -> bool:
        return computed is None or abs(computed - stored) < 0.6

    def distribution(scores: list[float]) -> dict[str, int]:
        dist: dict[str, int] = {}
        for s in scores:
            key = str(round(s))
            dist[key] = dist.get(key, 0) + 1
        return dist

    def dissenters(ratings: list[dict[str, Any]], group_mean: float | None) -> list[dict[str, Any]]:
        if group_mean is None:
            return []
        return [
            {"voterName": r.get("voterName") or "", "score": to_float(r.get("score"))}
            for r in ratings
            if abs(to_float(r.get("score")) - group_mean) > 1.0
        ]

    idea_data = []
    for idea in all_ideas:
        human_ratings = [r for r in idea["ratings"] if r.get("voterType") == "Human"]
        agent_ratings = [r for r in idea["ratings"] if r.get("voterType") == "Agent"]
        human_scores = [to_float(r.get("score")) for r in human_ratings]
        agent_scores = [to_float(r.get("score")) for r in agent_ratings]
        computed_human, computed_agent = mean(human_scores), mean(agent_scores)
        idea_data.append(
            {
                **idea,
                "humanRatings": human_ratings,
                "agentRatings": agent_ratings,
                "humanScores": human_scores,
                "agentScores": agent_scores,
                "computedHuman": computed_human,
                "computedAgent": computed_agent,
                "reconciles": reconciles(computed_human, idea["humanScore"])
                and reconciles(computed_agent, idea["agentScore"]),
                "gap": round(idea["agentScore"] - idea["humanScore"], 2),
            }
        )

    fidelity = "full" if all(d["reconciles"] for d in idea_data) else "aggregate"

    by_idea = []
    for d in idea_data:
        entry = {
            "ideaId": d["ideaId"],
            "track": d["track"],
            "agentId": d["agentId"],
            "title": d["title"],
            "humanScore": d["humanScore"],
            "agentScore": d["agentScore"],
            "overallScore": d["overallScore"],
            "gap": d["gap"],
            "humanVotes": {},
            "agentVotes": {},
        }
        if fidelity == "full":
            entry["humanVotes"] = {
                "count": len(d["humanRatings"]),
                "mean": round(d["computedHuman"], 2) if d["computedHuman"] is not None else None,
                "distribution": distribution(d["humanScores"]),
                "dissenters": dissenters(d["humanRatings"], d["computedHuman"]),
            }
            entry["agentVotes"] = {
                "count": len(d["agentRatings"]),
                "mean": round(d["computedAgent"], 2) if d["computedAgent"] is not None else None,
                "distribution": distribution(d["agentScores"]),
                "dissenters": dissenters(d["agentRatings"], d["computedAgent"]),
            }
        by_idea.append(entry)

    return {"fidelity": fidelity, "byIdea": by_idea}


@stage_node("build_foundation")
async def build_foundation(state: PipelineState) -> dict[str, Any]:
    req = get_request(state, SubstrateRequest)
    ten_step, ideas = req.ten_step_input, req.ideas_input

    agent_content = _build_agent_content(ten_step)
    entity_input = _build_entity_input(ten_step)

    facts_task = _call(
        "capstone_substrate.facts_register",
        FactsRegisterOutput,
        "agent_content_json",
        agent_content,
        "facts_register",
    )
    sig_task = _call(
        "capstone_substrate.entity_consolidation_signals",
        SigDecisionsOutput,
        "items_json",
        _slim_signals_or_uncertainties(entity_input["signals"]),
        "entity_signals",
    )
    unc_task = _call(
        "capstone_substrate.entity_consolidation_uncertainties",
        UncDecisionsOutput,
        "items_json",
        _slim_signals_or_uncertainties(entity_input["uncertainties"]),
        "entity_uncertainties",
    )
    bp_task = _call(
        "capstone_substrate.entity_consolidation_best_practices",
        BpDecisionsOutput,
        "items_json",
        _slim_best_practices(entity_input["bestPractices"]),
        "entity_best_practices",
    )
    action_map_input = _build_foresight_action_map_input(ten_step, ideas)
    action_task = _call(
        "capstone_substrate.foresight_action_map",
        ForesightActionMapOutput,
        "node6_input",
        action_map_input,
        "action_map",
    )

    facts_out, sig_out, unc_out, bp_out, action_out = await asyncio.gather(
        facts_task, sig_task, unc_task, bp_task, action_task
    )

    scenario_result = _assign_scenario_ids(entity_input["scenarios"])
    reconstructed = _reconstruct_entities(
        [d.model_dump(by_alias=True) for d in sig_out.sig_decisions],
        [d.model_dump(by_alias=True) for d in unc_out.unc_decisions],
        [d.model_dump(by_alias=True) for d in bp_out.bp_decisions],
        entity_input,
    )
    entities = {
        **reconstructed,
        "scenarios": scenario_result["scenarios"],
        "idMap": [*reconstructed["idMap"], *scenario_result["idMap"]],
    }
    divergence = _compute_divergence(ideas)

    return {
        "artifacts": {
            "facts": [f.model_dump(by_alias=True) for f in facts_out.facts],
            "entities": entities,
            "actionMap": action_out.model_dump(by_alias=True),
            "divergence": divergence,
        }
    }


# =====================================================================
# bind_and_cluster — Node 4b, Node 5
# =====================================================================


@stage_node("bind_and_cluster")
async def bind_and_cluster(state: PipelineState) -> dict[str, Any]:
    req = get_request(state, SubstrateRequest)
    entities = state["artifacts"]["entities"]

    node4b_input = {
        "signals": [{"signalId": s["signalId"], "title": s["title"]} for s in entities["signals"]],
        "uncertainties": _relational_binding_uncertainties(entities),
        "scenarios": [
            {"scenarioSetId": s["scenarioSetId"], "axesRaw": s["axesRaw"], "method": s["method"]}
            for s in entities["scenarios"]
        ],
        "idMap": entities["idMap"],
    }
    binding_out = await _call(
        "capstone_substrate.relational_binding",
        RelationalBindingOutput,
        "node4b_input",
        node4b_input,
        "relational_binding",
    )
    bindings = binding_out.model_dump(by_alias=True)

    metrics = req.ten_step_input.get("metrics") or {}
    single_contributor = (metrics.get("solutionContributorsCount") or 1) == 1
    binding_by_signal = {b["signalId"]: b for b in bindings["signalBindings"]}
    node5_input = {
        "signals": [
            {
                "signalId": s["signalId"],
                "title": s["title"],
                "domain": s["domain"],
                "tags": s.get("tags", []),
                "impact": s["impact"],
                "uncertainty": s["uncertainty"],
                "probability": s["probability"],
                "horizon": s["horizon"],
                "description": s["description"],
                "sourceAgents": s.get("sourceAgents", []),
                "becameScenarioAxis": binding_by_signal.get(s["signalId"], {}).get(
                    "becameScenarioAxis", False
                ),
                "axisRefs": binding_by_signal.get(s["signalId"], {}).get("axisRefs", []),
            }
            for s in entities["signals"]
        ],
        "singleContributor": single_contributor,
    }
    trends_out = await _call(
        "capstone_substrate.trend_clustering",
        TrendClusteringOutput,
        "node5_input",
        node5_input,
        "trend_clustering",
    )
    return {
        "artifacts": {
            "bindings": bindings,
            "trendsRaw": [t.model_dump(by_alias=True) for t in trends_out.trends],
        }
    }


def _relational_binding_uncertainties(entities: dict[str, Any]) -> list[dict[str, Any]]:
    """Port of the relatedWeakSignals/axis lookup inside "Relational Binding Input"."""
    related_raw_map: dict[Any, str] = {}
    # Original relatedWeakSignals text was on the raw weakSignals entries, not carried
    # through consolidation — resolved via variants/idMap lineage instead, matching n8n.
    axis_refs_by_original_id: dict[Any, list[Any]] = {}
    for scn in entities["scenarios"]:
        axes = scn.get("axesRaw") or {}
        for slot in ("axis1", "axis2", "focalPoint"):
            axis = axes.get(slot)
            if axis and axis.get("sourceId"):
                axis_refs_by_original_id.setdefault(axis["sourceId"], []).append(axis["sourceId"])

    out = []
    for u in entities["uncertainties"]:
        original_ids: list[Any] = []
        variants = u.get("variants")
        if variants:
            try:
                v = json.loads(variants) if isinstance(variants, str) else variants
                if isinstance(v, dict) and v.get("originalId"):
                    original_ids.append(v["originalId"])
            except (TypeError, ValueError):
                pass
        for entry in entities["idMap"]:
            if (
                entry.get("substrateId") == u["uncertaintyId"]
                and entry.get("originalId") not in original_ids
            ):
                original_ids.append(entry.get("originalId"))

        raw_texts = list({related_raw_map[oid] for oid in original_ids if oid in related_raw_map})
        axes_refs: set[Any] = set()
        for oid in original_ids:
            axes_refs.update(axis_refs_by_original_id.get(oid, []))

        out.append(
            {
                "uncertaintyId": u["uncertaintyId"],
                "title": u["title"],
                "relatedWeakSignalsRaw": "; ".join(raw_texts),
                "axesSourceRefsRaw": list(axes_refs),
            }
        )
    return out


# =====================================================================
# consolidate_recommendations — Node 7
# =====================================================================


@stage_node("consolidate_recommendations")
async def consolidate_recommendations(state: PipelineState) -> dict[str, Any]:
    req = get_request(state, SubstrateRequest)
    entities = state["artifacts"]["entities"]
    facts = state["artifacts"]["facts"]
    action_map = state["artifacts"]["actionMap"]

    per_agent = []
    for sol in req.ten_step_input.get("solutions", []):
        agent_id = (sol.get("agentInfo") or {}).get("agentId")
        form = sol.get("10StepForm") or {}
        step10 = form.get("step10") or {}
        opportunity_tree = []
        for opp in form.get("solutionOpportunities") or []:
            for ta in opp.get("termActionables") or []:
                if not isinstance(ta, dict):
                    continue
                for hi in ta.get("highImpactInitiatives") or []:
                    opportunity_tree.append(
                        {
                            "initiativeId": hi.get("initiativeId") or "",
                            "title": ta.get("title") or "",
                            "termType": hi.get("termType") or "",
                            "successLooksLike": hi.get("successLooksLike") or "",
                            "associatedCost": hi.get("associatedCost") or "",
                        }
                    )
        per_agent.append(
            {
                "agentId": agent_id,
                "step10Sections": {
                    "strategic_options_and_robustness": step10.get(
                        "strategic_options_and_robustness"
                    )
                    or "",
                    "action_pathways": step10.get("action_pathways") or "",
                    "implications_across_three_horizons": step10.get(
                        "implications_across_three_horizons"
                    )
                    or "",
                    "indicators_to_monitor": step10.get("indicators_to_monitor") or "",
                },
                "quickLongTermStrategies": form.get("quickLongTermStrategies") or "",
                "opportunityTree": opportunity_tree,
            }
        )

    node7_input = {
        "perAgentRecommendations": per_agent,
        "signals": [{"signalId": s["signalId"], "title": s["title"]} for s in entities["signals"]],
        "bestPractices": [
            {"bestPracticeId": b["bestPracticeId"], "title": b["title"]}
            for b in entities["bestPractices"]
        ],
        "facts": [{"factId": f["factId"], "statement": f["statement"]} for f in facts],
        "ideaToInitiative": [
            {
                "ideaId": m["ideaId"],
                "candidateInitiativeId": m.get("candidateInitiativeId"),
                "agentId": m["agentId"],
            }
            for m in action_map["ideaToInitiative"]
        ],
    }
    output = await _call(
        "capstone_substrate.recommendation_consolidation",
        RecommendationConsolidationOutput,
        "node7_input",
        node7_input,
        "recommendations",
    )
    return put_artifact("recommendations", output.model_dump(by_alias=True))


# =====================================================================
# lens_and_enrich — Node 9, Node 10
# =====================================================================


def _enrich_trends(
    trends: list[dict[str, Any]],
    action_map: dict[str, Any],
    recommendations: dict[str, Any],
    divergence: dict[str, Any],
) -> list[dict[str, Any]]:
    """Port of "(Node 10) Trend Prioritization Enrichment" — deterministic, no LLM."""
    settled = recommendations["settledRecommendations"]
    signal_to_recs: dict[str, list[str]] = {}
    for rec in settled:
        for sig_id in rec.get("supportingSignalIds", []):
            signal_to_recs.setdefault(sig_id, []).append(rec["recommendationId"])
    rec_to_ideas = {rec["recommendationId"]: rec.get("linkedIdeaIds", []) for rec in settled}
    idea_scores = {e["ideaId"]: e for e in divergence.get("byIdea", [])}

    enriched = []
    for trend in trends:
        rec_ids: set[str] = set()
        for sig_id in trend.get("memberSignalIds", []):
            rec_ids.update(signal_to_recs.get(sig_id, []))
        idea_ids: set[Any] = set()
        for rec_id in rec_ids:
            idea_ids.update(rec_to_ideas.get(rec_id, []))
        scored = [idea_scores[i] for i in idea_ids if i in idea_scores]
        if not scored:
            enriched.append(dict(trend))
            continue
        overall = [s["overallScore"] for s in scored]
        enriched.append(
            {
                **trend,
                "inheritedPriority": {
                    "derived": True,
                    "meanOverallScore": round(sum(overall) / len(overall), 2),
                    "maxOverallScore": max(overall),
                    "linkedIdeaCount": len(scored),
                    "linkedIdeaIds": [s["ideaId"] for s in scored],
                    "sourceRecIds": list(rec_ids),
                },
            }
        )
    return enriched


@stage_node("lens_and_enrich")
async def lens_and_enrich(state: PipelineState) -> dict[str, Any]:
    req = get_request(state, SubstrateRequest)
    entities = state["artifacts"]["entities"]
    recommendations = state["artifacts"]["recommendations"]

    per_agent_readings = []
    for sol in req.ten_step_input.get("solutions", []):
        agent_id = (sol.get("agentInfo") or {}).get("agentId")
        stakeholder = (sol.get("agentInfo") or {}).get("agentDesignation") or ""
        step10 = (sol.get("10StepForm") or {}).get("step10") or {}
        per_agent_readings.append(
            {
                "agentId": agent_id,
                "stakeholder": stakeholder,
                "step10": {
                    "stakeholder_context": step10.get("stakeholder_context") or "",
                    "signals_and_drivers_relevant_to_this_stakeholder": step10.get(
                        "signals_and_drivers_relevant_to_this_stakeholder"
                    )
                    or "",
                    "strategic_scenarios_stakeholder_specific_reading": step10.get(
                        "strategic_scenarios_stakeholder_specific_reading"
                    )
                    or "",
                    "critical_uncertainties_through_this_stakeholders_lens": step10.get(
                        "critical_uncertainties_through_this_stakeholders_lens"
                    )
                    or "",
                },
            }
        )
    stakeholders = list(dict.fromkeys(r["stakeholder"] for r in per_agent_readings))
    node9_input = {
        "stakeholders": stakeholders,
        "perAgentStakeholderReadings": per_agent_readings,
        "signals": [{"signalId": s["signalId"], "title": s["title"]} for s in entities["signals"]],
        "uncertainties": [
            {"uncertaintyId": u["uncertaintyId"], "title": u["title"]}
            for u in entities["uncertainties"]
        ],
        "settledRecommendations": [
            {"recommendationId": r["recommendationId"], "statement": r["statement"]}
            for r in recommendations["settledRecommendations"]
        ],
    }
    lens_task = _call(
        "capstone_substrate.stakeholder_lensing",
        StakeholderLensingOutput,
        "node9_input",
        node9_input,
        "stakeholder_lensing",
    )
    lens_out = await lens_task

    trends = _enrich_trends(
        state["artifacts"]["trendsRaw"],
        state["artifacts"]["actionMap"],
        recommendations,
        state["artifacts"]["divergence"],
    )
    return {
        "artifacts": {
            "stakeholderLensMap": lens_out.model_dump(by_alias=True)["stakeholderLensMap"],
            "trends": trends,
        }
    }


# =====================================================================
# future_and_investment — Node 7b, Node 7c
# =====================================================================


async def _consolidate_preferred_future(
    req: SubstrateRequest,
    entities: dict[str, Any],
    trends_raw: list[dict[str, Any]],
    facts: list[dict[str, Any]],
    sources: list[dict[str, Any]],
) -> dict[str, Any]:
    contributors = []
    for sol in req.ten_step_input.get("solutions", []):
        info = sol.get("agentInfo") or {}
        step10 = (sol.get("10StepForm") or {}).get("step10") or {}
        pf = (step10.get("the_preferred_future") or "").strip()
        uc = (step10.get("three_uncomfortable_conclusions") or "").strip()
        if not pf and not uc:
            continue
        contributors.append(
            {
                "agentId": info.get("agentId"),
                "stakeholder": info.get("agentDesignation") or info.get("agentName") or "",
                "preferredFutureText": pf,
                "uncomfortableConclusionsText": uc,
            }
        )
    if not contributors:
        return {"preferredFuture": None, "provocations": []}

    solutions = req.ten_step_input.get("solutions", [])
    node7b_input = {
        "meta": {"contributorCount": len(solutions), "singleContributor": len(solutions) == 1},
        "contributors": contributors,
        "scenarios": entities["scenarios"],
        "signals": entities["signals"],
        "trends": trends_raw,
        "facts": facts,
        "citations": sources,
    }
    output = await _call(
        "capstone_substrate.preferred_future",
        PreferredFutureOutput,
        "node7b_input",
        node7b_input,
        "preferred_future",
    )
    return output.model_dump(by_alias=True)


async def _size_investments(
    req: SubstrateRequest,
    recommendations: dict[str, Any],
    facts: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    entities: dict[str, Any],
) -> dict[str, Any]:
    settled = recommendations["settledRecommendations"]
    project = req.ten_step_input.get("project") or {}
    queries = [r["statement"][:200] for r in settled[:6] if r.get("statement")]
    results = await asyncio.gather(
        *(jina_search(q, top_k=3) for q in queries), return_exceptions=True
    )
    retrieved: list[dict[str, Any]] = []
    for r in results:
        if isinstance(r, BaseException):
            log.warning("capstone_substrate.investment_search_failed", error=str(r))
            continue
        retrieved.extend({"title": h.title, "url": h.url, "snippet": h.snippet} for h in r)

    node7c_input = {
        "settledRecommendations": settled,
        "facts": facts,
        "citations": sources,
        "bestPractices": entities["bestPractices"],
        "project": {
            "clientOrganization": project.get("clientOrganization") or "",
            "clientContext": project.get("clientContext") or "",
            "projectName": project.get("projectName") or "",
        },
        "retrievedResults": retrieved,
    }
    output = await _call(
        "capstone_substrate.investment_sizing",
        InvestmentSizingOutput,
        "node7c_input",
        node7c_input,
        "investment_sizing",
    )
    return _rollup_investment(output.model_dump(by_alias=True), settled, sources)


def _rollup_investment(
    sized: dict[str, Any], settled: list[dict[str, Any]], sources: list[dict[str, Any]]
) -> dict[str, Any]:
    """Port of "Investment Sizing Rollup" — deterministic, no LLM."""
    rec_ids = {r["recommendationId"] for r in settled}
    max_source_num = 0
    for s in sources:
        m = re.match(r"^S(\d+)$", s.get("sourceId", ""))
        if m:
            max_source_num = max(max_source_num, int(m.group(1)))
    added_sources = [
        {
            "sourceId": f"S{max_source_num + i + 1:03d}",
            "footnoteText": ", ".join(
                x
                for x in (
                    s.get("publisher"),
                    f'"{s["title"]}"' if s.get("title") else "",
                    s.get("date"),
                    s.get("url"),
                )
                if x
            ),
            "url": s.get("url"),
            "origin": "external-benchmark",
            "usedFor": s.get("usedFor", ""),
        }
        for i, s in enumerate(sized.get("newSources", []))
    ]

    violations = []
    clean = []
    for i, e in enumerate(sized.get("investmentEnvelopes", []), start=1):
        env = dict(e)
        env["investmentId"] = f"INV{i:03d}"
        env["indicative"] = True
        if env.get("recommendationId") not in rec_ids:
            violations.append(
                f"{env['investmentId']} references unknown recommendation "
                f"{env.get('recommendationId')}"
            )
        for key in ("capexRange", "opexAnnualRange"):
            r = env.get(key) or {}
            if (
                isinstance(r.get("low"), (int, float))
                and isinstance(r.get("high"), (int, float))
                and r["low"] > r["high"]
            ):
                r["low"], r["high"] = r["high"], r["low"]
        clean.append(env)

    covered = [e for e in clean if not e.get("unresolved")]
    currency = next(
        (e["capexRange"]["currency"] for e in covered if e.get("capexRange", {}).get("currency")),
        "USD",
    )
    by_horizon: dict[str, dict[str, int]] = {}
    for e in covered:
        for p in e.get("phasing", []):
            h = p.get("horizon") or "unspecified"
            by_horizon.setdefault(h, {"envelopeCount": 0})
            by_horizon[h]["envelopeCount"] += 1

    def sum_range(arr: list[dict[str, Any]], path: str, bound: str) -> float:
        return sum(
            (e.get(path) or {}).get(bound) or 0
            for e in arr
            if isinstance((e.get(path) or {}).get(bound), (int, float))
        )

    investment_summary = {
        "totalCapexRange": {
            "low": sum_range(covered, "capexRange", "low"),
            "high": sum_range(covered, "capexRange", "high"),
            "currency": currency,
        },
        "totalOpexAnnualRange": {
            "low": sum_range(covered, "opexAnnualRange", "low"),
            "high": sum_range(covered, "opexAnnualRange", "high"),
            "currency": currency,
        },
        "byHorizon": by_horizon,
        "coveredRecommendationIds": [e["recommendationId"] for e in covered],
        "uncoveredRecommendationIds": [
            rid for rid in rec_ids if not any(e["recommendationId"] == rid for e in covered)
        ],
        "envelopeCount": len(clean),
        "caveat": "All figures are indicative planning envelopes, not quotations. Ranges carry "
        "a stated basis and confidence; totals are the sum of sized recommendations only and "
        "exclude those the analysis could not size.",
        "rollupViolations": violations,
    }
    return {
        "investmentEnvelopes": clean,
        "investmentSummary": investment_summary,
        "addedSources": added_sources,
    }


@stage_node("future_and_investment")
async def future_and_investment(state: PipelineState) -> dict[str, Any]:
    req = get_request(state, SubstrateRequest)
    entities = state["artifacts"]["entities"]
    facts = state["artifacts"]["facts"]
    sources = state["artifacts"]["sources"]
    recommendations = state["artifacts"]["recommendations"]
    trends_raw = state["artifacts"]["trendsRaw"]

    pf_result, investment_result = await asyncio.gather(
        _consolidate_preferred_future(req, entities, trends_raw, facts, sources),
        _size_investments(req, recommendations, facts, sources, entities),
    )
    return {
        "artifacts": {"preferredFutureResult": pf_result, "investmentResult": investment_result}
    }


# =====================================================================
# assemble_substrate — Node 11
# =====================================================================


def _extract_nums(text: str) -> set[float]:
    return {float(n) for n in re.findall(r"\b\d+\.?\d*\b", text or "")}


def _assemble_substrate(state: PipelineState, req: SubstrateRequest) -> dict[str, Any]:
    """Port of "(Node 11) Substrate Assembly and Validation" — deterministic, no LLM."""
    metrics = req.ten_step_input.get("metrics") or {}
    contributor_count = metrics.get("solutionContributorsCount") or 1
    single_contributor = contributor_count == 1

    sources = state["artifacts"]["sources"]
    facts = state["artifacts"]["facts"]
    entities = state["artifacts"]["entities"]
    bindings = state["artifacts"]["bindings"]
    trends = state["artifacts"]["trends"]
    action_map = state["artifacts"]["actionMap"]
    recommendations = state["artifacts"]["recommendations"]
    divergence = state["artifacts"]["divergence"]
    stakeholder_lens_map = state["artifacts"]["stakeholderLensMap"]
    pf_result = state["artifacts"]["preferredFutureResult"]
    investment_result = state["artifacts"]["investmentResult"]

    signals, uncertainties, best_practices = (
        entities["signals"],
        entities["uncertainties"],
        entities["bestPractices"],
    )
    scenarios, id_map = entities["scenarios"], entities["idMap"]
    settled_recs = recommendations["settledRecommendations"]

    location_source_index: dict[str, list[str]] = {}
    for src in sources:
        for loc in src.get("contributingLocations", []):
            location_source_index.setdefault(loc, []).append(src["sourceId"])

    def to_ref_loc(content_loc: str) -> str:
        return re.sub(r"\|[^|]+$", "|solutionReferences", content_loc)

    def source_ids_for(locs: list[str]) -> list[str]:
        ids: set[str] = set()
        for loc in locs or []:
            ids.update(location_source_index.get(to_ref_loc(loc), []))
        return list(ids)

    corpus = [
        {
            "text": f"{s.get('description', '')} {s.get('implications', '')}",
            "locs": s.get("sourceLocations", []),
        }
        for s in [*signals, *uncertainties]
    ] + [
        {
            "text": f"{b.get('outcome', '')} {b.get('solutionText', '')} {b.get('challenge', '')}",
            "locs": b.get("sourceLocations", []),
        }
        for b in best_practices
    ]

    repaired_facts = []
    for fact in facts:
        if fact.get("citationKeys"):
            repaired_facts.append(fact)
            continue
        f_nums = _extract_nums(fact.get("statement", ""))
        matched: set[str] = set()
        for item in corpus:
            if not item["locs"]:
                continue
            i_nums = _extract_nums(item["text"])
            if any(n >= 10 and n in i_nums for n in f_nums):
                matched.update(source_ids_for(item["locs"]))
        repaired_facts.append(
            {**fact, "citationKeys": list(matched), "uncited": False} if matched else fact
        )

    valid_source_ids = {s["sourceId"] for s in sources}
    valid_fact_ids = {f["factId"] for f in repaired_facts}
    valid_signal_ids = {s["signalId"] for s in signals}
    valid_bp_ids = {b["bestPracticeId"] for b in best_practices}

    for rec in settled_recs:
        clean_keys = []
        for key in rec.get("citationKeys", []):
            if re.match(r"^S\d+$", key):
                if key in valid_source_ids:
                    clean_keys.append(key)
            elif re.match(r"^F\d+$", key):
                if key in valid_fact_ids:
                    clean_keys.append(key)
            elif re.match(r"^SIG\d+$", key):
                if key in valid_signal_ids and key not in rec.get("supportingSignalIds", []):
                    rec.setdefault("supportingSignalIds", []).append(key)
            elif (
                re.match(r"^BP\d+$", key)
                and key in valid_bp_ids
                and key not in rec.get("supportingBestPracticeIds", [])
            ):
                rec.setdefault("supportingBestPracticeIds", []).append(key)
        rec["citationKeys"] = clean_keys

    scenario_axes = {
        b["scenarioSetId"]: {
            "axis1Source": b.get("axis1Source"),
            "axis2Source": b.get("axis2Source"),
            "focalPointSource": b.get("focalPointSource"),
        }
        for b in bindings.get("scenarioBindings", [])
    }

    substrate: dict[str, Any] = {
        "meta": {
            "singleContributor": single_contributor,
            "contributorCount": contributor_count,
            "humanIdeatorCount": metrics.get("humanIdeatorCount") or 0,
            "agentContributorCount": metrics.get("agentContributorCount") or contributor_count,
        },
        "citations": {"sources": sources},
        "facts": repaired_facts,
        "signals": signals,
        "uncertainties": uncertainties,
        "bestPractices": best_practices,
        "scenarios": scenarios,
        "idMap": id_map,
        "signalBindings": bindings.get("signalBindings", []),
        "uncertaintyBindings": bindings.get("uncertaintyBindings", []),
        "scenarioAxes": scenario_axes,
        "trends": trends,
        "ideaToInitiative": action_map["ideaToInitiative"],
        "settledRecommendations": settled_recs,
        "minorityPositions": recommendations.get("minorityPositions", []),
        "divergence": divergence,
        "stakeholderLensMap": stakeholder_lens_map,
        "preferredFuture": pf_result.get("preferredFuture"),
        "provocations": pf_result.get("provocations", []),
        "investmentEnvelopes": investment_result["investmentEnvelopes"],
        "investmentSummary": investment_result["investmentSummary"],
    }

    violations: list[str] = []
    for f in repaired_facts:
        for key in f.get("citationKeys", []):
            if key not in valid_source_ids:
                violations.append(f'facts/{f["factId"]}: unresolved citationKey "{key}"')

    added_violations: list[str] = []
    fact_id_set = {f["factId"] for f in repaired_facts}
    source_id_set = {s["sourceId"] for s in sources}
    rec_id_set = {r["recommendationId"] for r in settled_recs}
    if substrate["preferredFuture"]:
        pf = substrate["preferredFuture"]
        if not str(pf.get("gapFromMostLikely") or "").strip():
            added_violations.append("preferredFuture carries no gap from the most likely future")
        for feature in pf.get("distinguishingFeatures", []):
            for fid in feature.get("factIds", []):
                if fid and fid not in fact_id_set:
                    added_violations.append(f"preferredFuture cites unknown fact {fid}")
        for key in pf.get("citationKeys", []):
            if key and key not in source_id_set:
                added_violations.append(f"preferredFuture cites unknown source {key}")
    for p in substrate["provocations"]:
        if not str(p.get("contradicts") or "").strip():
            added_violations.append(f"{p['provocationId']} names no belief it contradicts")
        if not p.get("supportingIds"):
            added_violations.append(f"{p['provocationId']} carries no supporting ids")
    for e in substrate["investmentEnvelopes"]:
        if e.get("recommendationId") not in rec_id_set:
            added_violations.append(
                f"{e['investmentId']} references unknown recommendation {e.get('recommendationId')}"
            )
        if e.get("indicative") is not True:
            added_violations.append(f"{e['investmentId']} is not marked indicative")
        for fid in e.get("anchorFactIds", []):
            if fid and fid not in fact_id_set:
                added_violations.append(f"{e['investmentId']} anchors on unknown fact {fid}")

    for s in investment_result.get("addedSources", []):
        if s["sourceId"] not in source_id_set:
            substrate["citations"]["sources"].append(s)

    substrate["integrityNotes"] = added_violations
    return {"substrate": substrate, "violations": [*violations, *added_violations]}


@stage_node("assemble_substrate")
async def assemble_substrate(state: PipelineState) -> dict[str, Any]:
    req = get_request(state, SubstrateRequest)
    result = _assemble_substrate(state, req)
    return put_artifact("assembly", result)


# =====================================================================
# review_and_finalize — Node 11b + callback
# =====================================================================


@stage_node("review_and_finalize")
async def review_and_finalize(state: PipelineState) -> dict[str, Any]:
    req = get_request(state, SubstrateRequest)
    assembly = state["artifacts"]["assembly"]
    substrate, violations = assembly["substrate"], assembly["violations"]

    node11b_input = {
        "substrate": substrate,
        "validationReport": {"validationFailed": bool(violations), "violations": violations},
    }
    review_out = await _call(
        "capstone_substrate.substrate_review",
        SubstrateReviewOutput,
        "node11b_input",
        node11b_input,
        "substrate_review",
    )
    review = review_out.model_dump(by_alias=True)
    # Deliberate fix: n8n computes this verdict but the export never actually
    # attaches it to the callback body — see module docstring.
    substrate["review"] = review

    callback = SubstrateCallback(
        session_id=req.session_id,
        project_id=req.project_id,
        trigger_batch_id=req.trigger_batch_id,
        status="completed",
        substrate=substrate,
        execution_id=state["run_id"],
    )
    return put_result(callback)


def build() -> StateGraph:
    g: StateGraph = StateGraph(PipelineState)
    g.add_node("resolve_citations", resolve_citations)
    g.add_node("build_foundation", build_foundation)
    g.add_node("bind_and_cluster", bind_and_cluster)
    g.add_node("consolidate_recommendations", consolidate_recommendations)
    g.add_node("lens_and_enrich", lens_and_enrich)
    g.add_node("future_and_investment", future_and_investment)
    g.add_node("assemble_substrate", assemble_substrate)
    g.add_node("review_and_finalize", review_and_finalize)

    g.add_edge(START, "resolve_citations")
    g.add_edge("resolve_citations", "build_foundation")
    g.add_edge("build_foundation", "bind_and_cluster")
    g.add_edge("bind_and_cluster", "consolidate_recommendations")
    g.add_edge("consolidate_recommendations", "lens_and_enrich")
    g.add_edge("lens_and_enrich", "future_and_investment")
    g.add_edge("future_and_investment", "assemble_substrate")
    g.add_edge("assemble_substrate", "review_and_finalize")
    g.add_edge("review_and_finalize", END)
    return g
