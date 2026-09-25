"""strategic_foresight_report stage I/O.

n8n source: no workflow export exists under this name in either
``challenges-n8n/`` or ``strategy-navigator-n8n/`` — but the operative prompt
(Mongo ``prompt_list`` id ``6``, "Report Generation") is fully recovered from
``strategy-navigator-n8n/Admin Workflows/Prompt seed.json``'s pinned webhook
payload (a byte-exact seed dump, not a truncated summary — see
``prompts/_mongo/6.md``). The ``5.1 n8n output parser schema`` section of that
prompt is the ground truth for :class:`StrategicForesightReportOutput` below;
every field name matches it exactly.

Trigger contract: backend's ``ProjectStrategicForesightReportWebhookPayload``
(project-strategic-foresight-report-webhook.dto.ts). Callback contract: backend's
``receiveProjectStrategicForesightReportFromN8n`` (customize-template.service.ts)
stores ``payload.output`` (or ``payload.strategyNavigatorReport``) verbatim as
opaque JSONB — no strict shape is enforced backend-side beyond ``sessionId``.
"""

from __future__ import annotations

from typing import Any

from strategy_navigator.schemas.common import CamelModel, ProjectContext


class StrategicForesightReportRequest(CamelModel):
    session_id: str
    project_id: int
    trigger_batch_id: str | None = None
    project: ProjectContext
    ideation_process: dict[str, Any] = {}
    project_ideas: list[Any] = []
    solutions: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {}
    target_audience: str = ""
    context_and_expectations: str = ""
    callback_url: str | None = None


class Priority(CamelModel):
    title: str
    score: str
    description: str
    strategic_significance: str


class QuickWin(CamelModel):
    action: str
    expected_outcome: str


class ExecutiveBrief(CamelModel):
    opening_paragraph: str
    top_5_priorities: list[Priority]
    methodology_note: str
    quick_wins: list[QuickWin]
    closing: str


class EvaluationFrameworkRow(CamelModel):
    criterion_name: str
    description: str
    weight_percent: str


class Part1ProcessAndParticipation(CamelModel):
    methodology: str
    participation_overview: str
    participation_flow_table: str
    evaluation_framework_table: list[EvaluationFrameworkRow]
    evaluation_framework_paragraphs: str
    quality_assurance: str


class ConvergencePoint(CamelModel):
    title: str
    description: str
    reinforcing_idea_ids: list[Any] = []


class DivergencePoint(CamelModel):
    title: str
    ai_view: str
    human_view: str
    practical_implication: str


class CategoryAnalysis(CamelModel):
    category_name: str
    idea_count: int
    top_score: str
    analysis: str
    convergence_points: list[ConvergencePoint] = []
    divergence_points: list[DivergencePoint] = []


class Part2FindingsAndAnalysis(CamelModel):
    portfolio_overview: str
    analysis_by_category: list[CategoryAnalysis]
    ai_human_alignment: str
    cross_category_synthesis: str


class RobustnessRow(CamelModel):
    idea_title: str
    status: str  # "ROBUST" | "CONDITIONAL" | "VULNERABLE"
    explanation: str


class Scenario(CamelModel):
    scenario_name: str
    description: str
    robustness_matrix: list[RobustnessRow] = []
    insights: str


class Part3ScenarioTesting(CamelModel):
    overview: str
    scenarios: list[Scenario]


class PriorityRow(CamelModel):
    rank: int
    idea_title: str
    score: str
    owner: str
    timeline: str


class ActionCard(CamelModel):
    action_id: str
    action_title: str
    owner: str
    start_month: int
    end_month: int
    resource_budget: str
    linked_ideas: list[Any] = []
    description: str
    success_criteria: list[Any] = []
    key_dependencies: list[Any] = []
    key_risks: str


class ActionQuickWin(CamelModel):
    action: str
    expected_30day_outcome: str


class MonitoringRow(CamelModel):
    metric_name: str
    baseline: str
    target: str
    frequency: str
    owner: str


class Part4StrategicActionPlan(CamelModel):
    priorities_table: list[PriorityRow]
    priorities_top3_rationale: list[str] = []
    sequencing_rationale: str
    timeline_table: str
    action_cards: list[ActionCard]
    quick_wins: list[ActionQuickWin]
    monitoring_table: list[MonitoringRow]
    adaptation_triggers: str


class KnowledgeGap(CamelModel):
    gap_title: str
    current_state: str
    why_it_matters: str
    recommended_research: str
    estimated_effort: str


class Part5KnowledgeGaps(CamelModel):
    overview: str
    gaps: list[KnowledgeGap]


class IdeaInventoryRow(CamelModel):
    id: str
    title: str
    category: str
    score: str
    source: str
    timeline: str


class Annexes(CamelModel):
    complete_idea_inventory: list[IdeaInventoryRow]
    evaluation_data_summary: str
    scenario_matrices: str


class StrategicForesightReportOutput(CamelModel):
    """Matches the prompt's own "5.1 n8n output parser schema" block verbatim."""

    executive_brief: ExecutiveBrief
    part1_process_and_participation: Part1ProcessAndParticipation
    part2_findings_and_analysis: Part2FindingsAndAnalysis
    part3_scenario_testing: Part3ScenarioTesting
    part4_strategic_action_plan: Part4StrategicActionPlan
    part5_knowledge_gaps: Part5KnowledgeGaps
    annexes: Annexes


class StrategicForesightReportCallback(CamelModel):
    """Matches what ``receiveProjectStrategicForesightReportFromN8n`` reads:
    ``payload.sessionId`` and ``payload.output`` (bare object; stored verbatim as
    opaque JSONB). ``tokenUsage``/``jinaTokens`` are read but optional — this repo's
    token accounting is automatic (see docs/MIGRATION-FROM-N8N.md), so we omit them.
    """

    session_id: str
    project_id: int
    output: dict[str, Any]
    execution_id: str | None = None
    token_usage: list[dict] | None = None
    error_message: str | None = None
