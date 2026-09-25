"""capstone_substrate stage I/O — the 13 distinct LLM call shapes.

n8n source: "Strategy Navigator Capstone Pipeline (4).json" (78 nodes). One
model per node's structured-output contract; see stages/capstone_substrate.py
for the graph and its module docstring for the node-by-node trace (the
deterministic Code nodes matter as much as the LLM ones here — several output
shapes below, e.g. the entity-consolidation "decisions" wrappers, were only
recoverable from the Code node that consumes them, not from the prompt text).
"""

from __future__ import annotations

from typing import Any

from pydantic import field_validator

from strategy_navigator.schemas.common import CamelModel

# --- Node 2: Citation Resolution ---------------------------------------------


class CitationAddition(CamelModel):
    matches_existing_id: str | None = None
    footnote_text: str = ""
    origin: str = "ideation"
    contributing_fragments: list[str] = []
    contributing_locations: list[str] = []


class CitationResolutionOutput(CamelModel):
    additions: list[CitationAddition] = []


# --- Node 3: Facts Register ---------------------------------------------------


class Fact(CamelModel):
    fact_id: str
    statement: str
    value: str | None = None
    unit: str | None = None
    as_of: str | None = None
    citation_keys: list[str] = []
    uncited: bool = False
    source_agents: list[int] = []

    @field_validator("value", mode="before")
    @classmethod
    def _coerce_numeric_value(cls, v: Any) -> Any:
        """Facts pair a bare ``value`` with a separate ``unit`` (e.g.
        value=10000, unit="INR crore"), so the LLM reasonably emits a
        numeric JSON value for numeric facts, not a pre-stringified one —
        confirmed live: 29 facts failed schema validation over 2 repair
        attempts (same value each time) because ``value`` only accepted
        ``str``."""
        return str(v) if isinstance(v, (int, float)) else v


class FactsRegisterOutput(CamelModel):
    facts: list[Fact] = []


# --- Node 4a: Entity Consolidation (signals / uncertainties / best practices) -


class SigDecision(CamelModel):
    signal_id: str
    member_original_ids: list[Any] = []
    title: str = ""
    domain: str = ""
    description_from: Any = None
    implications_from: Any = None
    impact: float | None = None
    uncertainty: float | None = None
    probability: float | None = None
    horizon: str = ""
    variants: str | None = None


class UncDecision(CamelModel):
    uncertainty_id: str
    member_original_ids: list[Any] = []
    title: str = ""
    domain: str = ""
    description_from: Any = None
    implications_from: Any = None
    impact: float | None = None
    uncertainty: float | None = None
    probability: float | None = None
    horizon: str = ""
    variants: str | None = None


class BpDecision(CamelModel):
    best_practice_id: str
    member_original_ids: list[Any] = []
    title_from: Any = None
    challenge_from: Any = None
    solution_text_from: Any = None
    outcome_from: Any = None
    implementation_from: Any = None


class SigDecisionsOutput(CamelModel):
    sig_decisions: list[SigDecision] = []


class UncDecisionsOutput(CamelModel):
    unc_decisions: list[UncDecision] = []


class BpDecisionsOutput(CamelModel):
    bp_decisions: list[BpDecision] = []


# --- Node 4b: Relational Binding ----------------------------------------------


class UncertaintyBinding(CamelModel):
    uncertainty_id: str
    driving_signal_ids: list[str] = []
    became_scenario_axis: bool = False
    axis_refs: list[dict[str, Any]] = []
    resolution_notes: str = ""


class SignalBinding(CamelModel):
    signal_id: str
    became_scenario_axis: bool = False
    axis_refs: list[dict[str, Any]] = []
    resolution_notes: str = ""


class ScenarioBinding(CamelModel):
    scenario_set_id: str
    axis1_source: dict[str, Any] | None = None
    axis2_source: dict[str, Any] | None = None
    focal_point_source: dict[str, Any] | None = None


class RelationalBindingOutput(CamelModel):
    uncertainty_bindings: list[UncertaintyBinding] = []
    signal_bindings: list[SignalBinding] = []
    scenario_bindings: list[ScenarioBinding] = []


# --- Node 5: Trend Clustering -------------------------------------------------


class Trend(CamelModel):
    trend_id: str
    label: str = ""
    member_signal_ids: list[str] = []
    source_agents: list[int] = []
    convergence: int = 0
    impact: float = 0
    uncertainty: float = 0
    horizon: str = ""
    confidence: str = "low"
    trajectory_basis: str = ""
    became_scenario_axis: bool = False
    axis_refs: list[dict[str, Any]] = []


class TrendClusteringOutput(CamelModel):
    trends: list[Trend] = []


# --- Node 6: Foresight-to-Action Map ------------------------------------------


class IdeaToInitiative(CamelModel):
    idea_id: int
    track: str
    agent_id: int | None = None
    candidate_initiative_id: str | None = None
    association_confidence: str = "none"
    association_basis: str = ""


class ForesightActionMapOutput(CamelModel):
    validation_present: bool = False
    idea_to_initiative: list[IdeaToInitiative] = []


# --- Node 7: Recommendation Consolidation -------------------------------------


class StretchVariant(CamelModel):
    statement: str = ""
    preconditions: list[str] = []
    first_proof_point: str = ""


class SettledRecommendation(CamelModel):
    recommendation_id: str
    statement: str = ""
    rationale: str = ""
    horizon: str = ""
    supporting_signal_ids: list[str] = []
    supporting_best_practice_ids: list[str] = []
    source_agents: list[int] = []
    linked_idea_ids: list[int] = []
    citation_keys: list[str] = []
    suggested_owner: str = ""
    dependencies: list[str] = []
    sequence_rank: int = 0
    stretch_variant: StretchVariant | None = None


class MinorityPosition(CamelModel):
    position_id: str
    statement: str = ""
    source_agents: list[int] = []
    why_excluded: str = ""
    what_would_elevate: str = ""


class RecommendationConsolidationOutput(CamelModel):
    settled_recommendations: list[SettledRecommendation] = []
    minority_positions: list[MinorityPosition] = []


# --- Node 8: Divergence (deterministic — no LLM; kept here for shape parity) -


class DivergenceIdeaEntry(CamelModel):
    idea_id: int
    track: str
    agent_id: int | None = None
    title: str = ""
    human_score: float = 0
    agent_score: float = 0
    overall_score: float = 0
    gap: float = 0
    human_votes: dict[str, Any] = {}
    agent_votes: dict[str, Any] = {}


class Divergence(CamelModel):
    fidelity: str = "aggregate"
    by_idea: list[DivergenceIdeaEntry] = []


# --- Node 9: Stakeholder Lensing ----------------------------------------------


class StakeholderLens(CamelModel):
    stakeholder: str
    relevant_signal_ids: list[str] = []
    relevant_uncertainty_ids: list[str] = []
    relevant_recommendation_ids: list[str] = []
    lens_notes: str = ""


class StakeholderLensingOutput(CamelModel):
    stakeholder_lens_map: list[StakeholderLens] = []


# --- Node 7b: Preferred Future and Provocations Consolidation ----------------


class DistinguishingFeature(CamelModel):
    feature: str = ""
    supporting_signal_ids: list[str] = []
    fact_ids: list[str] = []


class StakeholderEmphasis(CamelModel):
    agent_id: int
    stakeholder: str = ""
    emphasis: str = ""


class PreferredFuture(CamelModel):
    preferred_future_id: str = "PF001"
    statement: str = ""
    horizon_year: str = ""
    gap_from_most_likely: str = ""
    distinguishing_features: list[DistinguishingFeature] = []
    falsification_indicator: str = ""
    source_agents: list[int] = []
    stakeholder_emphases: list[StakeholderEmphasis] = []
    citation_keys: list[str] = []


class Provocation(CamelModel):
    provocation_id: str
    claim: str = ""
    contradicts: str = ""
    supporting_ids: list[str] = []
    if_true: str = ""
    source_agents: list[int] = []
    citation_keys: list[str] = []


class PreferredFutureOutput(CamelModel):
    preferred_future: PreferredFuture | None = None
    provocations: list[Provocation] = []


# --- Node 7c: Investment Sizing -----------------------------------------------


class MoneyRange(CamelModel):
    low: float = 0
    high: float = 0
    currency: str = "USD"
    note: str = ""


class InvestmentPhase(CamelModel):
    horizon: str = ""
    description: str = ""
    share_of_capex: str = ""


class Comparable(CamelModel):
    name: str = ""
    figure: str = ""
    citation_key: str = ""


class InvestmentEnvelope(CamelModel):
    investment_id: str = ""
    recommendation_id: str
    label: str = ""
    capex_range: MoneyRange = MoneyRange()
    opex_annual_range: MoneyRange = MoneyRange()
    phasing: list[InvestmentPhase] = []
    basis: str = "analyst-estimate"
    anchor_fact_ids: list[str] = []
    comparables: list[Comparable] = []
    assumptions: list[str] = []
    confidence: str = "low"
    indicative: bool = True
    citation_keys: list[str] = []
    unresolved: bool = False
    unresolved_reason: str = ""


class NewSource(CamelModel):
    url: str = ""
    title: str = ""
    publisher: str = ""
    date: str = ""
    used_for: str = ""


class InvestmentSizingOutput(CamelModel):
    investment_envelopes: list[InvestmentEnvelope] = []
    new_sources: list[NewSource] = []


# --- Node 11b: Substrate Review -----------------------------------------------


class SubstrateReviewFinding(CamelModel):
    finding_id: str
    check: str
    severity: str
    substrate_ids: list[str] = []
    quote_a: str = ""
    quote_b: str = ""
    issue: str = ""
    suggested_fix: str = ""


class SubstrateReviewOutput(CamelModel):
    verdict: str
    findings: list[SubstrateReviewFinding] = []
    passed_checks: list[str] = []
    summary_judgement: str = ""
