"""report_render stage I/O.

n8n source: "Report Render (3).json" (114 nodes). One structured-output model
per LLM node in the pipeline (see stages/report_render.py for the graph and
docs/MIGRATION-FROM-N8N.md's node-tracing notes). Complex nested QC objects
(reader personas, scorecard sub-sections) are kept as ``dict[str, Any]`` —
they are consumed as opaque context by the next stage, not field-validated,
matching the "permissive until fully needed" convention in this module.
"""

from __future__ import annotations

from typing import Any

from strategy_navigator.schemas.common import CamelModel


class RenderedSection(CamelModel):
    """One section, as produced by Section Generation, EDITORIAL, or QC 6."""

    section_name: str
    content: str
    citation_keys_used: list[str] = []
    fact_ids_used: list[str] = []
    external_option_ids_used: list[str] = []
    unfillable: bool = False
    word_count: int = 0


# --- Node 12: Engagement-Gap Detection ---------------------------------------


class NamedGap(CamelModel):
    gap_id: str
    description: str
    why_it_matters: str
    searchable: bool = True


class GapDetectionOutput(CamelModel):
    named_gaps: list[NamedGap] = []


# --- Node 13: External Search and Option Composition -------------------------


class ExternalOption(CamelModel):
    external_option_id: str
    answers_gap_id: str
    statement: str
    rationale: str
    footnote_text: str
    url: str | None = None


class ExistenceProof(CamelModel):
    existence_proof_id: str
    supports_claim_id: str
    claim_type: str
    what_the_source_shows: str
    disanalogy: str
    footnote_text: str
    url: str | None = None


class ExternalSearchOutput(CamelModel):
    external_options: list[ExternalOption] = []
    existence_proofs: list[ExistenceProof] = []


# --- Node 15: Render Planning -------------------------------------------------


class RenderPlanSection(CamelModel):
    section_name: str
    word_target: int
    tolerance_band: list[int] = [0, 0]
    emphasis: str = "supporting"
    section_rule: str = ""


class RenderPlan(CamelModel):
    total_word_budget: int = 0
    primary_reader: str = ""
    intended_use: str = "read"
    external_options_prominence: str = "note"
    divergence_display: str = "summary"
    search_budget: int = 5
    planning_notes: str = ""
    sections: list[RenderPlanSection] = []


class RenderPlanOutput(CamelModel):
    render_plan: RenderPlan


# --- Node 16: Fact-Currency Search Planning -----------------------------------


class FactCurrencyQuery(CamelModel):
    fact_id: str
    query: str
    reason: str


class FactCurrencyOutput(CamelModel):
    fact_currency_queries: list[FactCurrencyQuery] = []


# --- Node 19: Section Generation / EDITORIAL / QC 6 revised sections ---------


class SectionGenerationOutput(CamelModel):
    sections: list[RenderedSection] = []


# --- QC critics (first pass) --------------------------------------------------


class QCFinding(CamelModel):
    """Shared shape across QC1/QC2/QC C1 findings (extra fields ignored)."""

    finding_id: str
    section_name: str = ""
    section_names: list[str] = []
    category: str = ""
    check: str = ""
    severity: str
    quote: str = ""
    quote_a: str = ""
    quote_b: str = ""
    checked_against: str = ""
    substrate_ref: str = ""
    issue: str
    suggested_fix: str = ""


class QC1Output(CamelModel):
    critic: str = "traceability_auditor"
    findings: list[QCFinding] = []
    clean_sections: list[str] = []
    summary_judgement: str = ""


class QC2Output(CamelModel):
    critic: str = "coherence_checker"
    findings: list[QCFinding] = []
    passed_checks: list[str] = []
    summary_judgement: str = ""


class QC3Output(CamelModel):
    critic: str = "reader_persona_panel"
    readers: list[dict[str, Any]] = []
    convergent_issues: list[dict[str, Any]] = []
    summary_judgement: str = ""


class QC4Output(CamelModel):
    critic: str = "red_team"
    findings: list[dict[str, Any]] = []
    survived_attacks: list[dict[str, Any]] = []
    strongest_counterargument: str = ""
    summary_judgement: str = ""


class QC5Output(CamelModel):
    critic: str = "surprise_genericity_scorer"
    section_verdicts: list[dict[str, Any]] = []
    most_generic_paragraphs: list[dict[str, Any]] = []
    most_insight_dense: list[dict[str, Any]] = []
    truism_check: list[dict[str, Any]] = []
    non_obvious_claims: list[dict[str, Any]] = []
    surprise_verdict: dict[str, Any] = {}
    protection_list: list[dict[str, Any]] = []
    summary_judgement: str = ""


class QCC1Output(CamelModel):
    critic: str = "render_conformance"
    findings: list[QCFinding] = []
    passed_checks: list[str] = []
    summary_judgement: str = ""


# --- QC 6: Revision Agent -----------------------------------------------------


class ChangeLogEntry(CamelModel):
    finding_id: str
    section_name: str = ""
    action: str
    before: str = ""
    after: str = ""
    note: str = ""


class UnresolvedFinding(CamelModel):
    finding_id: str
    reason: str


class QC6Output(CamelModel):
    revised_sections: list[RenderedSection] = []
    change_log: list[ChangeLogEntry] = []
    unresolved: list[UnresolvedFinding] = []


# --- QC 7: Scorecard and Gate -------------------------------------------------


class QC7Output(CamelModel):
    gate: str
    gate_reasoning: str = ""
    open_findings: dict[str, Any] = {}
    disagreements: list[dict[str, Any]] = []
    section_completeness: dict[str, Any] = {}
    surprise_and_ambition: dict[str, Any] = {}
    certified_strengths: list[dict[str, Any]] = []
    strongest_counterargument: str = ""
    human_review_priorities: list[str] = []
    scorecard_markdown: str = ""


# --- mechanical audit (deterministic, no LLM) ---------------------------------


class MechanicalDefect(CamelModel):
    section_name: str
    defect_type: str
    detail: str
