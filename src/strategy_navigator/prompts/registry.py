"""Authoritative map of every LLM prompt in the pipeline and where it comes from.

Two things in the n8n export were surprising and drive this file:

1. The operative prompts for most stages are **not in the workflow JSON**. Each
   ``@n8n/n8n-nodes-langchain.agent`` node is set to ``text = {{ $json.prompt }}``
   and the template string is fetched at runtime from MongoDB, collection
   ``prompt_list``, by ``promptId``. A downstream ``Set`` node then substitutes
   ``${var}`` placeholders via ``String.replaceAll``. So the prompt *wording*
   lives in a database we do not have in git — only the ``promptId`` and the
   variable contract are recoverable from the export.

2. A few workflows (Report Render, Capstone Pipeline, Custom Archetype, and the
   generic summariser) *do* carry their prompt text inline in the node. Those are
   checked in verbatim under ``prompts/reference/`` and, where a stage is ported,
   as a normal block in ``<stage>.md``.

``PROMPTS`` below is the single source of truth. ``prompts.pull`` reads it to know
what to export from Mongo; the loader reads it to resolve a prompt ref to either a
Mongo-exported file (``prompts/_mongo/<promptId>.md``) or a local block.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from strategy_navigator.constants import Workflow


class PromptSource(StrEnum):
    #: template string lives in Mongo ``prompt_list`` — run scripts/pull_prompts.py
    MONGO = "mongo"
    #: prompt text is inline in the n8n node and checked in as a local block
    INLINE = "inline"


@dataclass(frozen=True)
class PromptSpec:
    ref: str
    """Dotted ref used by the loader, e.g. ``domain_agent.system``."""

    source: PromptSource
    workflow: Workflow
    n8n_workflow_file: str
    n8n_node: str
    """The ``agent`` / ``chainLlm`` node that consumes the rendered prompt."""

    prompt_id: str | None = None
    """Mongo ``prompt_list.promptId`` (``source == MONGO`` only)."""

    variables: tuple[str, ...] = ()
    """``${var}`` placeholders the n8n Set node substitutes, union across branches."""

    output_schema: str | None = None
    """``schemas`` class the structured output is validated against, if any."""

    local_block: str | None = None
    """Fallback block in ``<stage>.md`` used when the Mongo export is absent
    (dev / tests). ``None`` means the stage must have a real export to run."""

    port_diverges: bool = False
    """The LangGraph port does not match the n8n template's variable contract
    (e.g. voting scores a batch; the n8n lens prompts are per-idea). When True
    the export is kept for reference but ``render_prompt`` uses ``local_block``."""

    notes: str = ""

    @property
    def stage(self) -> str:
        return self.ref.split(".", 1)[0]


def _s(**kw: object) -> PromptSpec:
    return PromptSpec(**kw)  # type: ignore[arg-type]


# --- project-level variable contract -----------------------------------------
# Every Mongo template draws from some subset of these. ``prompts.bindings`` builds
# a dict with all of them populated from a ProjectContext / AgentRef so a
# template referencing any subset renders without a StrictUndefined error.
PROJECT_VARS: tuple[str, ...] = (
    "project_name",
    "project_title",  # alias used by some templates
    "client",  # alias for client_organization
    "client_org",
    "client_organization",
    "client_context",
    "project_description",
    "project_timelines",
    "time_horizon",  # alias for project_timelines
    "project_stakeholders",
    "stakeholders",  # alias, sometimes pre-joined
    "report_profile",
    "project_documents",
    "documents",  # alias
)
AGENT_VARS: tuple[str, ...] = (
    "agent_name",
    "agent_designation",
    "agent_description",
    "agent_type",
    "agent_stakeholder",
)


PROMPTS: dict[str, PromptSpec] = {
    # === domain_agent — n8n "Domain Specific Agent (1).json" ==================
    "domain_agent.system": _s(
        ref="domain_agent.system",
        source=PromptSource.MONGO,
        workflow=Workflow.DOMAIN_AGENT,
        n8n_workflow_file="Domain Specific Agent (1).json",
        n8n_node="AI Agent",
        prompt_id="1",
        variables=(
            "project_name",
            "client",
            "project_description",
            "project_timelines",
            "project_stakeholders",
            "project_documents",
        ),
        output_schema="schemas.domain.DomainAgentOutput",
        local_block="system",
        notes="Set nodes 'Edit Field' / 'Edit Field1' substitute vars; "
        "'Edit Field1' branch adds project_documents from summariser chains.",
    ),
    # === idea_extraction — n8n "Agent Idea Extraction with Project (2).json" ==
    "idea_extraction.system": _s(
        ref="idea_extraction.system",
        source=PromptSource.MONGO,
        workflow=Workflow.IDEA_EXTRACTION,
        n8n_workflow_file="Agent Idea Extraction with Project (2).json",
        n8n_node="AI Agent",
        prompt_id="2",
        variables=(
            "project_name",
            "project_description",
            "project_timelines",
            "client_org",
            "client_context",
            "report_profile",
            "project_stakeholders",
            "project_documents",
            "previous_agent_ideas",
            *AGENT_VARS,
        ),
        output_schema="schemas.ideas.IdeaExtractionOutput",
        local_block="system",
        notes="Branches 'Edit Field'/'Edit Field1'/'Edit Field2'/'Edit Field3' all "
        "feed promptId 2 with different var subsets (docs / cached ideas present or not).",
    ),
    "idea_extraction.document_ingestion": _s(
        ref="idea_extraction.document_ingestion",
        source=PromptSource.MONGO,
        workflow=Workflow.IDEA_EXTRACTION,
        n8n_workflow_file="Agent Idea Extraction with Project (2).json",
        n8n_node="Document Ingestion Agent",
        prompt_id="document_ingestion_prompt",
        variables=(
            "project_title",
            "project_description",
            "time_horizon",
            "stakeholders",
            "client_organization",
            "client_context",
            "documents",
            *AGENT_VARS,
        ),
        output_schema=None,
        local_block=None,
        notes="Fed by Set node 'Edit Field4'. Summarises uploaded docs before idea gen.",
    ),
    # === voting — n8n "Voting Agent (Child).json" ============================
    # Ten fixed lens agents + one contextual agent, each its own Mongo prompt.
    **{
        f"voting.{slug}": _s(
            ref=f"voting.{slug}",
            source=PromptSource.MONGO,
            workflow=Workflow.VOTING,
            n8n_workflow_file="Voting Agent (Child).json",
            n8n_node=f"{label} Prompt",
            prompt_id=pid,
            variables=(
                "project_name",
                "project_description",
                "ideaTitle",
                "ideaSummary",
                "ideaCategory",
                *((*AGENT_VARS,) if slug == "contextual" else ()),
            ),
            output_schema="schemas.voting.ChildVoteOutput",
            local_block="child_system",
            port_diverges=True,
            notes=f"Switch routes idea → {label} lens (per-idea, vars ${{ideaTitle}} "
            "etc.). Port scores a batch through the persona-driven child_system "
            "block; the export is reference for a future per-lens port.",
        )
        for slug, pid, label in [
            ("innovation", "5_innovation_agent_system_prompt", "Innovation Agent"),
            ("implementation", "5_implementation_agent_system_prompt", "Implementation Agent"),
            ("finance", "5_finance_agent_system_prompt", "Finance Agent"),
            ("impact", "5_impact_assessment_agent_system_prompt", "Impact Assessment"),
            ("technology", "5_technology_agent_system_prompt", "Technology Agent"),
            ("business", "5_business_agent_system_prompt", "Business Agent"),
            ("regulatory", "5_regulatory_agent_system_prompt", "Regulatory Agent"),
            ("sustainability", "5_sustainability_agent_system_prompt", "Sustainability Agent"),
            ("geopolitical", "5_geo_political_agent_system_prompt", "Geopolitical Agent"),
            ("contextual", "5_contextual_agent_system_prompt", "Contextual Agent"),
        ]
    },
    # === foresight_consolidation — n8n "Foresight Consolidation Agent.json" ===
    "foresight_consolidation.system": _s(
        ref="foresight_consolidation.system",
        source=PromptSource.MONGO,
        workflow=Workflow.FORESIGHT_CONSOLIDATION,
        n8n_workflow_file="Foresight Consolidation Agent.json",
        n8n_node="Foresight Consolidation Agent",
        prompt_id="8",
        variables=(
            "project_name",
            "project_description",
            "project_timelines",
            "client_org",
            "client_context",
            "report_profile",
            "project_stakeholders",
            "project_documents",
            "all_initiatives",
        ),
        local_block="system",
        notes="Set node 'Foresight Consolidation Prompt'. Stage not yet ported.",
    ),
    # === rapid_consolidation — n8n "Rapid Insight - Consolidation Agent.json" =
    "rapid_consolidation.a": _s(
        ref="rapid_consolidation.a",
        source=PromptSource.MONGO,
        workflow=Workflow.RAPID_CONSOLIDATION,
        n8n_workflow_file="Rapid Insight - Consolidation Agent.json",
        n8n_node="Consolidation Call A Agent",
        prompt_id="consolidation_a",
        variables=(
            "project_name",
            "project_description",
            "project_timelines",
            "client_org",
            "client_context",
            "report_profile",
            "project_stakeholders",
            "project_documents",
            "existing_ideas_with_comments",
        ),
        local_block="system",
    ),
    "rapid_consolidation.b": _s(
        ref="rapid_consolidation.b",
        source=PromptSource.MONGO,
        workflow=Workflow.RAPID_CONSOLIDATION,
        n8n_workflow_file="Rapid Insight - Consolidation Agent.json",
        n8n_node="Consolidation Call B Agent",
        prompt_id="consolidation_b",
        variables=(
            "project_name",
            "project_description",
            "project_timelines",
            "client_org",
            "client_context",
            "report_profile",
            "project_stakeholders",
            "project_documents",
            "consolidated_ideas",
            "document_comments",
        ),
        local_block=None,
    ),
    "rapid_consolidation.c": _s(
        ref="rapid_consolidation.c",
        source=PromptSource.MONGO,
        workflow=Workflow.RAPID_CONSOLIDATION,
        n8n_workflow_file="Rapid Insight - Consolidation Agent.json",
        n8n_node="Consolidation Call C Agent",
        prompt_id="consolidation_c",
        variables=(
            "project_name",
            "project_description",
            "project_timelines",
            "client_org",
            "client_context",
            "report_profile",
            "project_stakeholders",
            "project_documents",
            "consolidated_ideas",
            "document_idea_candidates",
            "ideator_new_ideas",
            "revised_existing_ideas",
        ),
        local_block=None,
    ),
    # === form_filling_10step — n8n "10 step form filling (3).json" ============
    # Steps 1-10 each pull promptId "3_<n>". Step 1 also takes project_timeline.
    **{
        f"form_filling_10step.step_{n}": _s(
            ref=f"form_filling_10step.step_{n}",
            source=PromptSource.MONGO,
            workflow=Workflow.FORM_FILLING_10STEP,
            n8n_workflow_file="10 step form filling (3).json",
            n8n_node=f"AI Agent{'' if n == 1 else n - 1}",
            prompt_id=f"3_{n}",
            variables=(
                "project_name",
                "project_description",
                *(("project_timeline",) if n == 1 else ()),
                "client_org",
                "client_context",
                "report_profile",
                "project_stakeholders",
                *AGENT_VARS,
            ),
            local_block=None,
            notes=f"Set node 'Step{n}Prompt'. Structured output repaired by 'Format Agent (s{n})'.",
        )
        for n in range(1, 11)
    },
    # === strategy_form_idea_generation — n8n "Strategy-form-idea-generation" ===
    "strategy_form_idea_generation.system": _s(
        ref="strategy_form_idea_generation.system",
        source=PromptSource.MONGO,
        workflow=Workflow.STRATEGY_FORM_IDEA_GENERATION,
        n8n_workflow_file="(Agent Idea Extraction with Project — solution branch)",
        n8n_node="AI Agent (solution)",
        prompt_id="4",
        variables=("json_solution", "previous_agent_ideas"),
        output_schema="schemas.ideas.IdeaExtractionOutput",
        local_block=None,
        notes="promptName 'Idea Extract with Solution'. Scores/curates ideas from "
        "the 10-step solution payload; not yet ported.",
    ),
    # === strategic_foresight_report — n8n "Report-Generation-Strategic-Foresight" =
    "strategic_foresight_report.system": _s(
        ref="strategic_foresight_report.system",
        source=PromptSource.MONGO,
        workflow=Workflow.STRATEGIC_FORESIGHT_REPORT,
        n8n_workflow_file="Report-Generation-Strategic-Foresight",
        n8n_node="AI Agent",
        prompt_id="6",
        variables=(
            "project_name",
            "project_description",
            "timeline",
            "project_stakeholders",
            "documents",
            "sessionId",
            "target_audience",
            "context_and_expectations",
            "project_ideas_dataset",
            "solutions_dataset",
        ),
        local_block=None,
        notes="promptName 'Report Generation'. Large publication-ready report "
        "prompt (n8n output parser schema); not yet ported.",
    ),
    # === voting contextual-panel generator — n8n "Contextual-voting-agent" =======
    "voting.panel_generator": _s(
        ref="voting.panel_generator",
        source=PromptSource.MONGO,
        workflow=Workflow.VOTING,
        n8n_workflow_file="Voting Middleware.json / Contextual-voting-agent",
        n8n_node="AI Agent",
        prompt_id="7",
        variables=(
            "project_name",
            "project_description",
            "project_stakeholders",
            "client",
            "project_timelines",
            "project_documents",
            "foundational_agents",
            "contextual_agents",
        ),
        output_schema="schemas.voting (agent panel)",
        local_block=None,
        notes="promptName 'Contextual Voting Agent'. Builds the evaluation panel "
        "(stakeholder / criteria / red-team agents) before scoring; not yet ported.",
    ),
    # === inline prompts (text is in the export, checked in as local blocks) ===
    "_shared.summarizer": _s(
        ref="_shared.summarizer",
        source=PromptSource.INLINE,
        workflow=Workflow.DOMAIN_AGENT,
        n8n_workflow_file="Domain Specific Agent (1).json",
        n8n_node="Basic LLM Chain / Basic LLM Chain2..4",
        local_block="summarizer",
        notes="Generic 'General Summarization Prompt (No Restrictions)'. "
        "Identical node appears in 10-step form filling and elsewhere.",
    ),
    "custom_archetype.system": _s(
        ref="custom_archetype.system",
        source=PromptSource.INLINE,
        workflow=Workflow.CUSTOM_ARCHETYPE,
        n8n_workflow_file="Custom archetype.json",
        n8n_node="AI Agent",
        output_schema="schemas.capstone.CustomArchetypeOutput",
        local_block="system",
        notes="Full text inline in the node — checked in verbatim.",
    ),
}


def get(ref: str) -> PromptSpec:
    try:
        return PROMPTS[ref]
    except KeyError:
        raise KeyError(f"Unknown prompt ref {ref!r}. Known refs: {sorted(PROMPTS)}") from None


def mongo_prompt_ids() -> list[str]:
    """Distinct Mongo ``promptId`` values the pipeline needs, for pull_prompts.py."""
    seen: dict[str, None] = {}
    for spec in PROMPTS.values():
        if spec.source is PromptSource.MONGO and spec.prompt_id:
            seen.setdefault(spec.prompt_id, None)
    return list(seen)


def specs_for(workflow: Workflow) -> list[PromptSpec]:
    return [s for s in PROMPTS.values() if s.workflow == workflow]
