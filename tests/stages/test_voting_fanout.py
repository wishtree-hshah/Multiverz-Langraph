"""voting graph fan-out: agents × idea-batches -> children -> aggregate."""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import MemorySaver

from strategy_navigator.graph.state import initial_state
from strategy_navigator.stages.voting import build


@pytest.fixture
def graph():
    return build().compile(checkpointer=MemorySaver())


async def test_every_agent_scores_every_idea(graph, fake_structured, sample_project):
    # each child returns a score per idea it is handed
    def _scores_for(ideas):
        return {"scores": [{"ideaId": i["id"], "score": 7.0, "rationale": "ok"} for i in ideas]}

    # fake_structured keys on stage; child stage is "score_batch". We need the
    # response to depend on the batch, so patch generate_structured directly.
    async def _gen(schema, messages, *, stage="-", **kw):
        # pull idea ids out of the user message
        import re

        ids = [int(x) for x in re.findall(r'"ideaId":\s*(\d+)', messages[-1]["content"])]
        return schema.model_validate(
            {"scores": [{"ideaId": i, "score": 7.0, "rationale": "ok"} for i in ids]}
        )

    import strategy_navigator.stages.voting.child as child_mod

    child_mod.generate_structured = _gen  # type: ignore[assignment]

    agents = [
        {"id": 1, "name": "A", "designation": "d", "description": "x"},
        {"id": 2, "name": "B", "designation": "d", "description": "x"},
    ]
    ideas = [{"id": 10, "title": "t10", "summary": "s"}, {"id": 11, "title": "t11", "summary": "s"}]

    state = initial_state(
        run_id="voting:b1",
        session_id="b1",
        workflow="voting",
        project_id=42,
        request={
            "sessionId": "b1",
            "batchId": "b1",
            "project": sample_project,
            "agents": agents,
            "ideas": ideas,
            "childBatchSize": 1,
        },
    )
    final = await graph.ainvoke(state, {"configurable": {"thread_id": "voting:b1"}})

    # Grouped per agent (the shape processAgentVotesAsync actually reads),
    # not a flat list — each agent's ratings use "rating"/"comment", not
    # ChildVoteOutput's "score"/"rationale".
    agents = final["result"]["agents"]
    assert {a["agentId"] for a in agents} == {1, 2}
    rated_pairs = {
        (a["agentId"], r["ideaId"]) for a in agents for r in a["ratings"]
    }
    assert rated_pairs == {(1, 10), (1, 11), (2, 10), (2, 11)}
    assert all(r["rating"] == 7.0 and r["comment"] == "ok" for a in agents for r in a["ratings"])
