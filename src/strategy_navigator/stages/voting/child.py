"""Voting child: one agent scores one batch of ideas."""

from __future__ import annotations

from typing import Any

from strategy_navigator.graph.state import PipelineState
from strategy_navigator.llm.structured import generate_structured
from strategy_navigator.logging import get_logger
from strategy_navigator.prompts import bindings, render, render_prompt
from strategy_navigator.schemas.common import AgentRef
from strategy_navigator.schemas.voting import ChildVoteOutput, VotingRequest
from strategy_navigator.stages.base import get_request, stage_node

log = get_logger(__name__)


@stage_node("score_batch")
async def score_batch(state: PipelineState) -> dict[str, Any]:
    child = state["_child"]  # type: ignore[typeddict-item]
    agent = AgentRef.model_validate(child["agent"])
    ideas = child["ideas"]
    req = get_request(state, VotingRequest)

    prompt_vars = bindings.build(req.project, agent=agent)
    # Port note: n8n routes each idea to one of 10 Mongo lens prompts
    # (registry: voting.innovation .. voting.contextual). The port scores a
    # batch through the agent's own persona; contextual is the closest match.
    system = render_prompt("voting.contextual", **prompt_vars)
    user = render("voting.child_user", ideas_json=_ideas_json(ideas), **prompt_vars)

    output = await generate_structured(
        ChildVoteOutput,
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        stage="score_batch",
        temperature=0.2,
    )

    votes = [
        {
            "agentId": agent.id,
            "ideaId": s.idea_id,
            "score": s.score,
            "rationale": s.rationale,
        }
        for s in output.scores
    ]
    log.info("voting.child_done", agent_id=agent.id, batch=child["batch_index"], votes=len(votes))
    return {"partials": votes}


def _ideas_json(ideas: list[dict]) -> str:
    import orjson

    slim = [{"ideaId": i["id"], "title": i["title"], "summary": i["summary"]} for i in ideas]
    return orjson.dumps(slim, option=orjson.OPT_INDENT_2).decode()
