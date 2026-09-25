"""form_filling_10step stage I/O.

n8n source: "10 step form filling (3).json" (308 nodes — the largest export,
but most of its bulk is n8n-specific durability plumbing: a per-step
Resolve-Deps/Fetch-Prior/Assemble-Ctx/Shape-Save/Save-Output/Restore/
Delete-Prior apparatus that exists to make an n8n execution resumable after a
crash. LangGraph's own Postgres checkpointer already provides that; it is not
ported. See stages/form_filling_10step.py's module docstring for the full
trace.

Step output shapes are typed permissively (top-level keys the prompt's own
"Output Format" section documents; array items as ``dict[str, Any]``) —
the committed Mongo prompts (prompts/_mongo/3_1.md .. 3_10.md) are condensed
exports that describe most nested item shapes in prose rather than a literal
JSON schema, so pinning exact field names here would be guessing, not
porting. This matches the established convention in schemas/capstone.py for
semi-structured content.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from strategy_navigator.schemas.common import AgentRef, CamelModel, ProjectContext


class FormFillingRequest(CamelModel):
    session_id: str
    project: ProjectContext
    agent: AgentRef
    log_id: int | None = None
    completed_steps: dict[str, Any] = {}
    callback_url: str | None = None


class StepCheckpoint(CamelModel):
    """Matches backend's ``N8nStepCheckpointDto`` exactly — posted once per
    step (mid-run, via ``callbacks.client.post_step_checkpoint``) for steps
    1-9, and once more as step 10's final result via the normal queue-task
    callback delivery (no separate "submission" endpoint exists; see the
    stage module docstring).
    """

    run_id: str
    step_number: int
    step_key: str
    output: dict[str, Any]
    execution_id: str | None = None
    token_usage: list[dict] | None = None
    jina_tokens: int | None = None


# --- Step 1: Problem Definition + Breakdown + Info Assessment + Solution ----


class Step1Output(CamelModel):
    define_problem: str = ""
    problem_breakdown: str = ""
    info_assessment: str = ""
    solution_exploration_innovation: str = ""
    solution_implementation: str = ""
    problem_challenge_synthesis: str = ""


# --- Step 2: Best Practices --------------------------------------------------


class Step2Output(CamelModel):
    best_practices: list[dict[str, Any]] = []
    solution_references: dict[str, Any] = {}
    next_practices: str = ""


# --- Step 3: Weak Signals & Uncertainties ------------------------------------


class Step3Output(CamelModel):
    weak_signals: list[dict[str, Any]] = []
    uncertainties: list[dict[str, Any]] = []
    drivers_of_change: str = ""


# --- Step 4: Scenario Frameworks + Preferred Future --------------------------


class ScenarioSet(CamelModel):
    """One scenario-set: GBN model under root key "0", Four Step model under
    "1". ``axes`` stays permissive (its shape differs by method — GBN carries
    axis1/axis2/quadrantMap, Four Step carries focalPoint/progression/
    scenarioMap — and capstone_substrate.py only ever forwards it raw as
    ``axesRaw``). The scalar fields below ARE read by exact name downstream
    (capstone_substrate.py's entity-consolidation input does
    ``sf.get("scenarioAnalysisKeyInsight")``), so they're pinned here rather
    than left in a free-form dict: an earlier live run had the LLM drift to
    "analysisKeyInsight" instead of the prompt's own "scenarioAnalysisKey
    Insight", which silently dropped that field for every downstream reader
    since nothing enforced the name.
    """

    type: str = ""
    axes: dict[str, Any] = {}
    scenario_a: str = ""
    scenario_b: str = ""
    scenario_c: str = ""
    scenario_d: str = ""
    weak_signal1: str = ""
    weak_signal2: str = ""
    scenario_synthesis: str = ""
    scenario_analysis_key_insight: str = ""


class Step4Output(CamelModel):
    """Root keys "0" (GBN model) / "1" (Four Step model) come back as-is —
    n8n's own port (node "Code in JavaScript6") just tags each with a
    ``type``/``axes.method`` label, ported in ``_tag_scenario_methods``.
    """

    field_0: ScenarioSet | None = Field(default=None, alias="0")
    field_1: ScenarioSet | None = Field(default=None, alias="1")
    preferred_future: str = ""
    solution_references: dict[str, Any] = {}


# --- Step 5: Research Synthesis ----------------------------------------------


class Step5Output(CamelModel):
    key_insights: str = ""
    opportunity_spaces: str = ""
    risk_resilience: str = ""
    innovation_pathways: str = ""
    quick_long_term_strategies: str = ""
    solution_references: dict[str, Any] = {}


# --- Step 6: Solution Term Opportunities (near/medium/long) -----------------


class Step6Output(CamelModel):
    solution_term_opportunities: list[dict[str, Any]] = []
    solution_references: dict[str, Any] = {}


# --- Step 7: High-Priority Term Actionables ----------------------------------


class Step7Output(CamelModel):
    high_priority_term_actionable: list[dict[str, Any]] = []
    solution_references: dict[str, Any] = {}


# --- Step 8: Immediate Actions -----------------------------------------------


class ImmediateAction(CamelModel):
    title: str
    term_type: str
    priority_score: int = 0
    rank: int = 0


class Step8Output(CamelModel):
    immediate_actions: list[ImmediateAction] = []
    solution_references: dict[str, Any] = {}


# --- Step 9: Executive Summary + Future Press Release ------------------------


class Step9Solution(CamelModel):
    executive_summary: str = ""
    future_press_release: str = ""


class Step9Output(CamelModel):
    solution: Step9Solution = Step9Solution()
    solution_references: dict[str, Any] = {}


# --- Step 10: Strategic Foresight Report (16-section stakeholder report) ----


class Step10Output(CamelModel):
    masthead: str = ""
    executive_summary: str = ""
    key_figures: str = ""
    three_uncomfortable_conclusions: str = ""
    stakeholder_context: str = ""
    methodology_note: str = ""
    signals_and_drivers_relevant_to_this_stakeholder: str = ""
    critical_uncertainties_through_this_stakeholders_lens: str = ""
    strategic_scenarios_stakeholder_specific_reading: str = ""
    the_preferred_future: str = ""
    implications_across_three_horizons: str = ""
    strategic_options_and_robustness: str = ""
    indicators_to_monitor: str = ""
    action_pathways: str = ""
    annexes: str = ""
    references: str = ""
