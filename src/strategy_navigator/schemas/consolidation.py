"""rapid_consolidation stage I/O (n8n Consolidation-agent webhook).

Mirrors challenges-backend/src/components/n8n/dto/webhook/consolidation-webhook.dto.ts
"""

from __future__ import annotations

from typing import Literal

from strategy_navigator.schemas.common import CamelModel, Idea, ProjectContext, Tier


class ConsolidationIdeaInput(CamelModel):
    title: str
    summary: str
    sources: list[str] = []
    categories: list[str] = []
    type: Literal["rapid", "strategic", "human"] | None = None
    comments: list[str] = []


class ConsolidationAgentGroup(CamelModel):
    id: int
    name: str
    designation: str | None = None
    description: str | None = None
    agent_type: Literal["foundational", "contextual", "human"]
    is_domain_specific: bool = False
    stakeholder: str | None = None
    ideas: list[ConsolidationIdeaInput] = []


class ConsolidationRequest(CamelModel):
    session_id: str
    project: ProjectContext
    agents: list[ConsolidationAgentGroup]
    consolidation_type: Literal["agent", "human"] | None = None
    callback_url: str | None = None


class ConsolidatedIdea(CamelModel):
    title: str
    summary: str
    sources: list[str] = []
    categories: list[str] = []
    agent_id: int
    is_domain_specific_agent: bool = False
    tier: Tier | None = None


class ConsolidationOutput(CamelModel):
    ideas: list[ConsolidatedIdea]


class ConsolidationCallback(CamelModel):
    session_id: str
    ideas: list[Idea]
    execution_id: str | None = None
    token_usage: list[dict] | None = None
    consolidation_type: Literal["agent", "human"] | None = None
    error_message: str | None = None
