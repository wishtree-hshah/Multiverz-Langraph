"""Workflow identifiers and their mapping to n8n.

The ``Workflow`` enum values are the canonical internal names. ``N8N_WORKFLOW_NAME``
maps each to the string the challenges-backend sends in ``{ workflow_name, payload }``
(see challenges-backend/src/components/n8n/constants/n8n-workflow-names.ts), so the
webhook layer can accept the exact same triggers the backend already emits.
"""

from __future__ import annotations

from enum import StrEnum


class Workflow(StrEnum):
    DOMAIN_AGENT = "domain_agent"
    IDEA_EXTRACTION = "idea_extraction"
    STRATEGY_FORM_IDEA_GENERATION = "strategy_form_idea_generation"
    FORM_FILLING_10STEP = "form_filling_10step"
    RAPID_CONSOLIDATION = "rapid_consolidation"
    FORESIGHT_CONSOLIDATION = "foresight_consolidation"
    VOTING = "voting"
    CAPSTONE_SUBSTRATE = "capstone_substrate"
    REPORT_RENDER = "report_render"
    CUSTOM_ARCHETYPE = "custom_archetype"
    STRATEGIC_FORESIGHT_REPORT = "strategic_foresight_report"


class Lane(StrEnum):
    SHORT = "short"
    LONG = "long"
    RETRY = "retry"


# challenges-backend N8N_WORKFLOW_NAMES  ->  internal Workflow
N8N_WORKFLOW_NAME: dict[str, Workflow] = {
    "Domain-specific-agent-generation": Workflow.DOMAIN_AGENT,
    "Agent-ideas": Workflow.IDEA_EXTRACTION,
    "Strategy-form-idea-generation": Workflow.STRATEGY_FORM_IDEA_GENERATION,
    "Strategy-form-submission": Workflow.FORM_FILLING_10STEP,
    "Consolidation-agent": Workflow.RAPID_CONSOLIDATION,
    "Foresight-consolidation-agent": Workflow.FORESIGHT_CONSOLIDATION,
    "Voting-agent": Workflow.VOTING,
    "Contextual-voting-agent": Workflow.VOTING,
    "Capstone-Substrate-Generation": Workflow.CAPSTONE_SUBSTRATE,
    "Capstone-Report-Render": Workflow.REPORT_RENDER,
    "Capstone-Custom-Archetype-Author": Workflow.CUSTOM_ARCHETYPE,
    "Report-Generation-Strategic-Foresight": Workflow.STRATEGIC_FORESIGHT_REPORT,
}

# Which lane each workflow runs in. Mirrors the challenges-n8n bulkhead
# (4 short slots / 6 heavy slots).
WORKFLOW_LANE: dict[Workflow, Lane] = {
    Workflow.DOMAIN_AGENT: Lane.SHORT,
    Workflow.IDEA_EXTRACTION: Lane.SHORT,
    Workflow.STRATEGY_FORM_IDEA_GENERATION: Lane.SHORT,
    Workflow.RAPID_CONSOLIDATION: Lane.SHORT,
    Workflow.FORESIGHT_CONSOLIDATION: Lane.SHORT,
    Workflow.VOTING: Lane.SHORT,
    Workflow.FORM_FILLING_10STEP: Lane.LONG,
    Workflow.CAPSTONE_SUBSTRATE: Lane.LONG,
    Workflow.REPORT_RENDER: Lane.LONG,
    Workflow.CUSTOM_ARCHETYPE: Lane.LONG,
    Workflow.STRATEGIC_FORESIGHT_REPORT: Lane.LONG,
}

# procrastinate job priority (higher runs first). Retries jump ahead of fresh
# work; human-gate resumes beat fresh work but yield to retries.
PRIORITY_FRESH = 0
PRIORITY_HUMAN_RESUME = 50
PRIORITY_RETRY = 100
