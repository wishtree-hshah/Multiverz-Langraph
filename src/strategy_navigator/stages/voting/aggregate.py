"""Voting aggregate: collect all child votes into the callback body.

Equivalent of "Voting Middleware.json" — dedupe, sanity-check completeness,
shape the VotingCallback the backend's voting callback endpoint expects.
"""

from __future__ import annotations

from typing import Any

from strategy_navigator.graph.state import PipelineState
from strategy_navigator.logging import get_logger
from strategy_navigator.schemas.voting import (
    AgentRating,
    AgentVote,
    AgentVoteGroup,
    VotingCallback,
    VotingRequest,
)
from strategy_navigator.stages.base import get_request, put_result, stage_node

log = get_logger(__name__)


@stage_node("aggregate")
async def aggregate(state: PipelineState) -> dict[str, Any]:
    req = get_request(state, VotingRequest)
    raw: list[dict] = state.get("partials", [])

    # last-write-wins dedupe on (agentId, ideaId)
    by_key: dict[tuple[int, int], AgentVote] = {}
    for v in raw:
        by_key[(v["agentId"], v["ideaId"])] = AgentVote(
            agent_id=v["agentId"], idea_id=v["ideaId"], score=v["score"], rationale=v["rationale"]
        )

    expected = len(req.agents) * len(req.ideas)
    if len(by_key) != expected:
        log.warning("voting.incomplete", got=len(by_key), expected=expected)

    # Group the flat (agent, idea) votes back into one entry per agent — the
    # shape challenges-backend's callback handler actually reads.
    agent_names = {a.id: a.name for a in req.agents}
    ratings_by_agent: dict[int, list[AgentRating]] = {}
    for vote in sorted(by_key.values(), key=lambda v: (v.agent_id, v.idea_id)):
        ratings_by_agent.setdefault(vote.agent_id, []).append(
            AgentRating(idea_id=vote.idea_id, rating=vote.score, comment=vote.rationale)
        )
    agent_groups = [
        AgentVoteGroup(agent_id=agent_id, agent_name=agent_names.get(agent_id), ratings=ratings)
        for agent_id, ratings in sorted(ratings_by_agent.items())
    ]

    callback = VotingCallback(
        session_id=req.session_id,
        batch_id=req.batch_id or req.session_id,
        voting_session_id=req.voting_session_id,
        agents=agent_groups,
        execution_id=state["run_id"],
    )
    return put_result(callback)
