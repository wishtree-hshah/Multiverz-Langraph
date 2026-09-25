"""idea_extraction stage I/O (n8n Agent-ideas webhook)."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from strategy_navigator.schemas.common import AgentRef, CamelModel, ProjectContext


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
    """Matches what ``receiveAgentIdeasFromN8n``/``receiveAgentIdeasFromN8nBody``
    (customize-template.service.ts) actually reads: a bare object keyed by
    ``runId`` (not ``sessionId`` — this is the one callback in this repo that
    uses that name), with ``results`` (not ``ideas``). ``projectId`` is
    deliberately absent — the backend looks it up from its own trigger log
    (``log.rawPayload.projectId``), not from the callback body. Confirmed live
    against a real backend: sending the old {sessionId, projectId, ideas: [...]}
    shape 400s with "Invalid response format: expected object with results array".
    """

    run_id: str
    agent_id: int
    agent_source: str | None = None  # "domain-specific" when agent.isDomainSpecific
    results: list[ExtractedIdea]
    token_usage: list[dict] | None = None
    error_message: str | None = None


# --- strategy_form_idea_generation -------------------------------------------
# n8n "Strategy-form-idea-generation" — no workflow export exists, but the
# operative prompt (Mongo prompt_list id "4", "Idea Extract with Solution") is
# recovered byte-exact from strategy-navigator-n8n's Prompt seed.json (see
# prompts/_mongo/4.md). Trigger contract: CustomizeTemplateService.processIdea
# (challenges-backend) POSTs a bare ARRAY of one item per customized template,
# all sharing one runId. Callback contract: receiveSolutionExtractedIdeasFromN8n
# expects back an array of {runId, user, project, templateId, results: [...]}
# rows (one per template) — see payload_adapter._adapt_strategy_form_idea_generation.


class FormIdeaTemplateInput(CamelModel):
    """One item of the trigger array's ``solution`` block."""

    template_id: int | None = None
    project_id: int
    project_name: str = ""
    project_description: str = ""
    template_solution: dict[str, Any] = {}


class FormIdeaGenerationRequest(CamelModel):
    session_id: str  # == the shared runId
    project_id: int
    templates: list[FormIdeaTemplateInput] = Field(min_length=1)
    usermetadata: dict[str, Any] = {}
    callback_url: str | None = None


class FormIdeaGenerationRow(CamelModel):
    """One echo-back row in the callback array — matches what
    ``receiveSolutionExtractedIdeasFromN8nBody`` reads off each array item."""

    run_id: str
    user: dict[str, Any]
    project: dict[str, Any]
    template_id: int | None
    results: list[ExtractedIdea]


class FormIdeaGenerationCallback(CamelModel):
    """The whole POST body: ``{"results": [...]}`` — a bare object whose
    ``results`` key the backend controller unwraps into the per-template array
    (no top-level ``runId`` on this wrapper, so the "agent-generated" branch of
    ``receiveSolutionExtractedIdeasFromN8n`` is not mistakenly taken)."""

    results: list[FormIdeaGenerationRow]
