"""idea_extraction stage I/O (n8n Agent-ideas webhook)."""

from __future__ import annotations

from pydantic import Field

from strategy_navigator.schemas.common import AgentRef, CamelModel, Idea, ProjectContext


class IdeaExtractionRequest(CamelModel):
    session_id: str
    project: ProjectContext
    agent: AgentRef
    categories: list[str] = []
    documents: list[str] = []
    idea_count: int = 5
    research_queries: list[str] = []
    callback_url: str | None = None


class ExtractedIdea(CamelModel):
    title: str
    summary: str
    sources: list[str] = []
    categories: list[str] = []


class IdeaExtractionOutput(CamelModel):
    ideas: list[ExtractedIdea] = Field(min_length=1)


class IdeaExtractionCallback(CamelModel):
    session_id: str
    project_id: int
    agent_id: int
    ideas: list[Idea]
    execution_id: str | None = None
    token_usage: list[dict] | None = None
    error_message: str | None = None
