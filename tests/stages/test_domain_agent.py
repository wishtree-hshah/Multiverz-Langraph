"""domain_agent graph, compiled with an in-memory checkpointer (no Postgres)."""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import MemorySaver

from strategy_navigator.graph.state import initial_state
from strategy_navigator.stages.domain_agent import build


@pytest.fixture
def graph():
    return build().compile(checkpointer=MemorySaver())


async def test_domain_agent_produces_callback(graph, fake_structured, sample_project):
    fake_structured.set(
        "generate_personas",
        {
            "personas": [
                {"name": "Dr Ada Vane", "designation": "Grid Economist", "description": "..."},
                {"name": "Ravi Kohl", "designation": "Ops Reliability Lead", "description": "..."},
            ]
        },
    )
    state = initial_state(
        run_id="domain_agent:s1",
        session_id="s1",
        workflow="domain_agent",
        project_id=42,
        request={
            "sessionId": "s1",
            "project": sample_project,
            "documents": [],
            "minAgents": 2,
            "maxAgents": 4,
        },
    )
    config = {"configurable": {"thread_id": "domain_agent:s1"}}
    final = await graph.ainvoke(state, config)

    result = final["result"]
    assert result["sessionId"] == "s1"
    assert result["projectId"] == 42
    assert len(result["agents"]) == 2
    assert result["agents"][0]["name"] == "Dr Ada Vane"


async def test_domain_agent_survives_bad_document(
    graph, fake_structured, sample_project, monkeypatch
):
    async def _boom(ref: str, **kw):
        raise RuntimeError("s3 down")

    monkeypatch.setattr("strategy_navigator.stages.domain_agent.extract_document_text", _boom)
    fake_structured.set(
        "generate_personas", {"personas": [{"name": "X", "designation": "Y", "description": "Z"}]}
    )

    state = initial_state(
        run_id="domain_agent:s2",
        session_id="s2",
        workflow="domain_agent",
        project_id=42,
        request={
            "sessionId": "s2",
            "project": {**sample_project, "documents": ["broken.pdf"]},
            "minAgents": 1,
            "maxAgents": 2,
        },
    )
    final = await graph.ainvoke(state, {"configurable": {"thread_id": "domain_agent:s2"}})
    assert final["result"]["agents"][0]["name"] == "X"
