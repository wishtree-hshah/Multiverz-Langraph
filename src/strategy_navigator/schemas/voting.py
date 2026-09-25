"""voting stage I/O (n8n Voting-agent / Contextual-voting-agent webhook)."""

from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator

from strategy_navigator.schemas.common import AgentRef, CamelModel, ProjectContext


class VotingIdea(CamelModel):
    id: int
    title: str
    summary: str
    categories: list[str] = []

    @field_validator("categories", mode="before")
    @classmethod
    def _coerce_category_names(cls, v: Any) -> Any:
        """Backend sends each idea's categories as ``{id, name}`` objects
        (same shape used across its voting/ideas-listing endpoints), not bare
        strings — confirmed live: a plain ``list[str]`` rejected every idea
        with a Pydantic validation error before the graph could even start,
        so the run never got a real ``votingSessionId`` to echo back either."""
        if not isinstance(v, list):
            return v
        return [item.get("name", "") if isinstance(item, dict) else item for item in v]


class VotingRequest(CamelModel):
    session_id: str  # backend sends batchId here
    batch_id: str | None = None
    voting_session_id: int | None = None
    project: ProjectContext
    agents: list[AgentRef]
    ideas: list[VotingIdea]
    callback_url: str | None = None
    child_batch_size: int = 10  # ideas per child task


class IdeaScore(CamelModel):
    idea_id: int = Field(alias="ideaId")
    score: float = Field(ge=0, le=10)
    rationale: str


class ChildVoteOutput(CamelModel):
    scores: list[IdeaScore]


class AgentVote(CamelModel):
    """Flat (agent, idea) vote — the aggregate node's own internal dedup unit,
    keyed (agent_id, idea_id). NOT the wire shape: challenges-backend's
    ``processAgentVotesAsync`` expects votes grouped per agent (see
    ``AgentVoteGroup``/``VotingCallback`` below), not a flat list.
    """

    agent_id: int
    idea_id: int
    score: float
    rationale: str


class AgentRating(CamelModel):
    """One idea's rating from one agent, in the exact shape
    ``VotingSessionService.saveAgentVotes``/``processAgentVotesAsync`` read:
    field names ``rating``/``comment``, NOT ``score``/``rationale`` — those
    are ``ChildVoteOutput``'s names for what we ask the LLM to produce, but
    the callback's wire contract (matching the old n8n workflow's output,
    which backend was built against) uses different field names entirely.
    """

    idea_id: int
    rating: float = Field(ge=0, le=10)
    comment: str


class AgentVoteGroup(CamelModel):
    agent_id: int
    agent_name: str | None = None
    ratings: list[AgentRating] = []


class VotingCallback(CamelModel):
    session_id: str
    batch_id: str | None = None
    voting_session_id: int | None = None
    # Nested per-agent groups, NOT a flat list — confirmed live: a flat
    # ``votes: list[AgentVote]`` (this file's earlier shape) delivered a 201
    # but processAgentVotesAsync's `payload?.agents` check silently found
    # nothing, logged "No agents data found", and persisted zero ratings.
    agents: list[AgentVoteGroup]
    execution_id: str | None = None
    token_usage: list[dict] | None = None
    error_message: str | None = None
