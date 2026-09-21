"""foresight_consolidation stage I/O (n8n Foresight-consolidation-agent webhook)."""

from __future__ import annotations

from typing import Any, Literal

from strategy_navigator.schemas.common import CamelModel, Horizon, Idea, ProjectContext, Tier


class ForesightSolutionItem(CamelModel):
    source_agent: str  # "foundational:{id}" | "domain:{id}"
    agent_name: str
    agent_designation: str | None = None
    agent_type: Literal["foundational", "contextual"]
    is_domain_specific: bool = False
    stakeholder: str | None = None
    opportunities: list[dict[str, Any]] = []


class ForesightConsolidationRequest(CamelModel):
    session_id: str
    project: ProjectContext
    solutions: list[ForesightSolutionItem]
    callback_url: str | None = None


class ForesightConsolidatedIdea(CamelModel):
    title: str
    summary: str
    sources: list[str] = []
    categories: list[str] = []
    source_agents: list[str]
    tier: Tier | None = None
    horizon: Horizon | None = None


class ForesightConsolidationOutput(CamelModel):
    ideas: list[ForesightConsolidatedIdea]


class ForesightConsolidationCallback(CamelModel):
    session_id: str
    ideas: list[Idea]
    execution_id: str | None = None
    token_usage: list[dict] | None = None
    error_message: str | None = None
