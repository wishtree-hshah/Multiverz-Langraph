"""voting stage I/O (n8n Voting-agent / Contextual-voting-agent webhook)."""

from __future__ import annotations

from pydantic import Field

from strategy_navigator.schemas.common import AgentRef, CamelModel, ProjectContext


class VotingIdea(CamelModel):
    id: int
    title: str
    summary: str
    categories: list[str] = []


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
    agent_id: int
    idea_id: int
    score: float
    rationale: str


class VotingCallback(CamelModel):
    session_id: str
    batch_id: str | None = None
    voting_session_id: int | None = None
    votes: list[AgentVote]
    execution_id: str | None = None
    token_usage: list[dict] | None = None
    error_message: str | None = None
