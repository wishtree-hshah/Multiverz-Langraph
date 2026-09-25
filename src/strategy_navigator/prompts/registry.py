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
        "the 10-step solution payload. Ported (stages/strategy_form_idea_generation.py); "
        "byte-exact text recovered from strategy-navigator-n8n's Prompt seed.json "
        "pinned payload (no n8n workflow export exists under this name).",
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
        "prompt (n8n output parser schema). Ported (stages/strategic_foresight_report.py); "
        "byte-exact text (including the full 5.1 output-parser JSON schema) recovered "
        "from strategy-navigator-n8n's Prompt seed.json pinned payload (no n8n workflow "
        "export exists under this name).",
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
    # === report_render — n8n "Report Render (3).json" (114 nodes) ============
    # Traced node-by-node from the export's Code/If connections; see
    # stages/report_render.py's module docstring.
    "report_render.gap_detection": _s(
        ref="report_render.gap_detection",
        source=PromptSource.INLINE,
        workflow=Workflow.REPORT_RENDER,
        n8n_workflow_file="Report Render (3).json",
        n8n_node="(Node 12) Engagement-Gap Detection",
        output_schema="schemas.report_render.GapDetectionOutput",
        local_block="gap_detection",
    ),
    "report_render.external_search": _s(
        ref="report_render.external_search",
        source=PromptSource.INLINE,
        workflow=Workflow.REPORT_RENDER,
        n8n_workflow_file="Report Render (3).json",
        n8n_node="(Node 13) External Search and Option Composition1",
        output_schema="schemas.report_render.ExternalSearchOutput",
        local_block="external_search",
        notes="n8n node has a web search tool attached; ported as jina_search "
        "results composed into the prompt rather than an agentic tool loop.",
    ),
    "report_render.render_planning": _s(
        ref="report_render.render_planning",
        source=PromptSource.INLINE,
        workflow=Workflow.REPORT_RENDER,
        n8n_workflow_file="Report Render (3).json",
        n8n_node="(Node 15) Render Planning",
        output_schema="schemas.report_render.RenderPlanOutput",
        local_block="render_planning",
    ),
    "report_render.fact_currency_planning": _s(
        ref="report_render.fact_currency_planning",
        source=PromptSource.INLINE,
        workflow=Workflow.REPORT_RENDER,
        n8n_workflow_file="Report Render (3).json",
        n8n_node="(Node 16) Fact-Currency Search Planning",
        output_schema="schemas.report_render.FactCurrencyOutput",
        local_block="fact_currency_planning",
        notes="Node 17 'Search Execution' downstream is a pure data passthrough "
        "in the export (no search call wired to it) — ported the same way.",
    ),
    "report_render.section_generation": _s(
        ref="report_render.section_generation",
        source=PromptSource.INLINE,
        workflow=Workflow.REPORT_RENDER,
        n8n_workflow_file="Report Render (3).json",
        n8n_node="(Node 19) Section Generation",
        output_schema="schemas.report_render.SectionGenerationOutput",
        local_block="section_generation",
        notes="n8n branches long (>15 pages, per-section loop) vs short (batch) "
        "path via '(Node 18) Length Branch'; ported as the short/batch path only.",
    ),
    "report_render.editorial": _s(
        ref="report_render.editorial",
        source=PromptSource.INLINE,
        workflow=Workflow.REPORT_RENDER,
        n8n_workflow_file="Report Render (3).json",
        n8n_node="EDITORIAL / EDITORIAL3",
        output_schema="schemas.report_render.RenderedSection",
        local_block="editorial",
        notes="EDITORIAL and EDITORIAL3 are byte-identical prompts — n8n's own "
        "retry-once-on-empty-output node (see node 'If'). Ported as one prompt "
        "called up to twice per section.",
    ),
    "report_render.qc1_traceability": _s(
        ref="report_render.qc1_traceability",
        source=PromptSource.INLINE,
        workflow=Workflow.REPORT_RENDER,
        n8n_workflow_file="Report Render (3).json",
        n8n_node="QC 1: Traceability Auditor (+ Traceability Auditor1 recheck)",
        output_schema="schemas.report_render.QC1Output",
        local_block="qc1_traceability",
        notes="Reused verbatim for the post-revision recheck pass.",
    ),
    "report_render.qc2_coherence": _s(
        ref="report_render.qc2_coherence",
        source=PromptSource.INLINE,
        workflow=Workflow.REPORT_RENDER,
        n8n_workflow_file="Report Render (3).json",
        n8n_node="QC 2: Coherence Checker (+ Coherence Checker1 recheck)",
        output_schema="schemas.report_render.QC2Output",
        local_block="qc2_coherence",
        notes="Reused verbatim for the post-revision recheck pass.",
    ),
    "report_render.qc3_reader_panel": _s(
        ref="report_render.qc3_reader_panel",
        source=PromptSource.INLINE,
        workflow=Workflow.REPORT_RENDER,
        n8n_workflow_file="Report Render (3).json",
        n8n_node="QC 3: Reader Persona Panel",
        output_schema="schemas.report_render.QC3Output",
        local_block="qc3_reader_panel",
        notes="First pass only — not rechecked after revision.",
    ),
    "report_render.qc4_red_team": _s(
        ref="report_render.qc4_red_team",
        source=PromptSource.INLINE,
        workflow=Workflow.REPORT_RENDER,
        n8n_workflow_file="Report Render (3).json",
        n8n_node="QC 4: Red Team Critic",
        output_schema="schemas.report_render.QC4Output",
        local_block="qc4_red_team",
        notes="First pass only — not rechecked after revision.",
    ),
    "report_render.qc5_genericity": _s(
        ref="report_render.qc5_genericity",
        source=PromptSource.INLINE,
        workflow=Workflow.REPORT_RENDER,
        n8n_workflow_file="Report Render (3).json",
        n8n_node="QC 5: Surprise and Genericity Scorer",
        output_schema="schemas.report_render.QC5Output",
        local_block="qc5_genericity",
        notes="First pass only — not rechecked after revision.",
    ),
    "report_render.qc_c1_conformance": _s(
        ref="report_render.qc_c1_conformance",
        source=PromptSource.INLINE,
        workflow=Workflow.REPORT_RENDER,
        n8n_workflow_file="Report Render (3).json",
        n8n_node="QC C1: Render Conformance and Provenance Boundary (+ recheck)",
        output_schema="schemas.report_render.QCC1Output",
        local_block="qc_c1_conformance",
        notes="Reused verbatim for the post-revision recheck pass.",
    ),
    "report_render.qc6_revision": _s(
        ref="report_render.qc6_revision",
        source=PromptSource.INLINE,
        workflow=Workflow.REPORT_RENDER,
        n8n_workflow_file="Report Render (3).json",
        n8n_node="QC 6: Revision Agent",
        output_schema="schemas.report_render.QC6Output",
        local_block="qc6_revision",
        notes="Only runs when Consolidate Findings 1's hasBlockerOrMajor is true "
        "(n8n node 'If2'); at most one cycle (n8n has no loop back to QC1-5).",
    ),
    "report_render.qc7_scorecard": _s(
        ref="report_render.qc7_scorecard",
        source=PromptSource.INLINE,
        workflow=Workflow.REPORT_RENDER,
        n8n_workflow_file="Report Render (3).json",
        n8n_node="QC 7: Scorecard and Gate",
        output_schema="schemas.report_render.QC7Output",
        local_block="qc7_scorecard",
    ),
    # === capstone_substrate — n8n "Strategy Navigator Capstone Pipeline (4).json" (78 nodes) ===
    # Traced node-by-node from the export's Code/connections; see
    # stages/capstone_substrate.py's module docstring.
    "capstone_substrate.citation_resolution": _s(
        ref="capstone_substrate.citation_resolution",
        source=PromptSource.INLINE,
        workflow=Workflow.CAPSTONE_SUBSTRATE,
        n8n_workflow_file="Strategy Navigator Capstone Pipeline (4).json",
        n8n_node="(Node 2) Citation Resolution",
        output_schema="schemas.capstone_substrate.CitationResolutionOutput",
        local_block="citation_resolution",
        notes="Runs after a deterministic URL-dedup pre-pass (node "
        "'Code in JavaScript2') that builds sources/proseResidual; only "
        "resolves the leftover prose citations.",
    ),
    "capstone_substrate.facts_register": _s(
        ref="capstone_substrate.facts_register",
        source=PromptSource.INLINE,
        workflow=Workflow.CAPSTONE_SUBSTRATE,
        n8n_workflow_file="Strategy Navigator Capstone Pipeline (4).json",
        n8n_node="(Node 3) Facts Register",
        output_schema="schemas.capstone_substrate.FactsRegisterOutput",
        local_block="facts_register",
        notes="Receives only agentContent (no sources table, despite what the "
        "prompt's own prose describes) — verified against the actual "
        "'Facts Register Input' Code node. Every fact starts uncited; "
        "citations are repaired later by number-matching against signals/"
        "uncertainties/best-practices text (node 'Node 11' equivalent).",
    ),
    "capstone_substrate.entity_consolidation_signals": _s(
        ref="capstone_substrate.entity_consolidation_signals",
        source=PromptSource.INLINE,
        workflow=Workflow.CAPSTONE_SUBSTRATE,
        n8n_workflow_file="Strategy Navigator Capstone Pipeline (4).json",
        n8n_node="(Node 4a) Entity Consolidation",
        output_schema="schemas.capstone_substrate.SigDecisionsOutput",
        local_block="entity_consolidation_signals",
        notes="Output wrapper key 'sigDecisions' confirmed from the "
        "reconstruction Code node ('Code in JavaScript'), not from the "
        "prompt text (which never shows the wrapper key).",
    ),
    "capstone_substrate.entity_consolidation_uncertainties": _s(
        ref="capstone_substrate.entity_consolidation_uncertainties",
        source=PromptSource.INLINE,
        workflow=Workflow.CAPSTONE_SUBSTRATE,
        n8n_workflow_file="Strategy Navigator Capstone Pipeline (4).json",
        n8n_node="(Node 4a) Entity Consolidation2",
        output_schema="schemas.capstone_substrate.UncDecisionsOutput",
        local_block="entity_consolidation_uncertainties",
    ),
    "capstone_substrate.entity_consolidation_best_practices": _s(
        ref="capstone_substrate.entity_consolidation_best_practices",
        source=PromptSource.INLINE,
        workflow=Workflow.CAPSTONE_SUBSTRATE,
        n8n_workflow_file="Strategy Navigator Capstone Pipeline (4).json",
        n8n_node="(Node 4a) Entity Consolidation3",
        output_schema="schemas.capstone_substrate.BpDecisionsOutput",
        local_block="entity_consolidation_best_practices",
    ),
    "capstone_substrate.relational_binding": _s(
        ref="capstone_substrate.relational_binding",
        source=PromptSource.INLINE,
        workflow=Workflow.CAPSTONE_SUBSTRATE,
        n8n_workflow_file="Strategy Navigator Capstone Pipeline (4).json",
        n8n_node="(Node 4b) Relational Binding",
        output_schema="schemas.capstone_substrate.RelationalBindingOutput",
        local_block="relational_binding",
    ),
    "capstone_substrate.trend_clustering": _s(
        ref="capstone_substrate.trend_clustering",
        source=PromptSource.INLINE,
        workflow=Workflow.CAPSTONE_SUBSTRATE,
        n8n_workflow_file="Strategy Navigator Capstone Pipeline (4).json",
        n8n_node="(Node 5) Trend Clustering",
        output_schema="schemas.capstone_substrate.TrendClusteringOutput",
        local_block="trend_clustering",
    ),
    "capstone_substrate.foresight_action_map": _s(
        ref="capstone_substrate.foresight_action_map",
        source=PromptSource.INLINE,
        workflow=Workflow.CAPSTONE_SUBSTRATE,
        n8n_workflow_file="Strategy Navigator Capstone Pipeline (4).json",
        n8n_node="(Node 6) Foresight-to-Action Map",
        output_schema="schemas.capstone_substrate.ForesightActionMapOutput",
        local_block="foresight_action_map",
    ),
    "capstone_substrate.recommendation_consolidation": _s(
        ref="capstone_substrate.recommendation_consolidation",
        source=PromptSource.INLINE,
        workflow=Workflow.CAPSTONE_SUBSTRATE,
        n8n_workflow_file="Strategy Navigator Capstone Pipeline (4).json",
        n8n_node="(Node 7) Recommendation Consolidation",
        output_schema="schemas.capstone_substrate.RecommendationConsolidationOutput",
        local_block="recommendation_consolidation",
    ),
    "capstone_substrate.stakeholder_lensing": _s(
        ref="capstone_substrate.stakeholder_lensing",
        source=PromptSource.INLINE,
        workflow=Workflow.CAPSTONE_SUBSTRATE,
        n8n_workflow_file="Strategy Navigator Capstone Pipeline (4).json",
        n8n_node="(Node 9) Stakeholder Lensing",
        output_schema="schemas.capstone_substrate.StakeholderLensingOutput",
        local_block="stakeholder_lensing",
    ),
    "capstone_substrate.preferred_future": _s(
        ref="capstone_substrate.preferred_future",
        source=PromptSource.INLINE,
        workflow=Workflow.CAPSTONE_SUBSTRATE,
        n8n_workflow_file="Strategy Navigator Capstone Pipeline (4).json",
        n8n_node="(Node 7b) Preferred Future and Provocations Consolidation",
        output_schema="schemas.capstone_substrate.PreferredFutureOutput",
        local_block="preferred_future",
    ),
    "capstone_substrate.investment_sizing": _s(
        ref="capstone_substrate.investment_sizing",
        source=PromptSource.INLINE,
        workflow=Workflow.CAPSTONE_SUBSTRATE,
        n8n_workflow_file="Strategy Navigator Capstone Pipeline (4).json",
        n8n_node="(Node 7c) Investment Sizing",
        output_schema="schemas.capstone_substrate.InvestmentSizingOutput",
        local_block="investment_sizing",
        notes="n8n node has a web search tool attached; ported as jina_search "
        "results composed into the prompt, same pattern as report_render's "
        "external_search. Totals/ids assigned deterministically downstream "
        "('Investment Sizing Rollup').",
    ),
    "capstone_substrate.substrate_review": _s(
        ref="capstone_substrate.substrate_review",
        source=PromptSource.INLINE,
        workflow=Workflow.CAPSTONE_SUBSTRATE,
        n8n_workflow_file="Strategy Navigator Capstone Pipeline (4).json",
        n8n_node="(Node 11b) Substrate Review",
        output_schema="schemas.capstone_substrate.SubstrateReviewOutput",
        local_block="substrate_review",
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
