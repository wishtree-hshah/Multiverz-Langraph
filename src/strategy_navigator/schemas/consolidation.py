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


class ConsolidationDocumentComment(CamelModel):
    document_key: str
    comments: list[str] = []


class ConsolidationRequest(CamelModel):
    session_id: str
    project: ProjectContext
    agents: list[ConsolidationAgentGroup]
    document_comments: list[ConsolidationDocumentComment] = []
    consolidation_type: Literal["agent", "human"] | None = None
    callback_url: str | None = None


class RevisedIdea(CamelModel):
    """One item of Call A's (revise) or Call C's (new) output array."""

    title: str
    summary: str
    sources: list[str] = []
    categories: list[str] = []
    provenance: Literal["revised-existing", "new"] | None = None
    tier: Tier | None = None


class RevisedIdeasOutput(CamelModel):
    ideas: list[RevisedIdea]


class DocumentHighlight(CamelModel):
    document: str
    summary: str
    key_insights: list[str] = []


class DocumentIdeaCandidate(CamelModel):
    title: str
    summary: str
    sources: list[str] = []


class DocumentCommentaryOutput(CamelModel):
    """Call B's output: consolidated per-document commentary + surfaced candidates."""

    document_highlights: list[DocumentHighlight] = []
    idea_candidates: list[DocumentIdeaCandidate] = []


class ConsolidatedIdea(CamelModel):
    title: str
    summary: str
    sources: list[str] = []
    categories: list[str] = []
    agent_id: int | None = None
    is_domain_specific_agent: bool | None = None
    tier: Tier | None = None


class ConsolidationCallback(CamelModel):
    session_id: str
    ideas: list[Idea]
    execution_id: str | None = None
    token_usage: list[dict] | None = None
    consolidation_type: Literal["agent", "human"] | None = None
    error_message: str | None = None
