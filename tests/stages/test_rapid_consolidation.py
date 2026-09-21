"""rapid_consolidation graph (Call A/B/C chain), compiled with an in-memory
checkpointer."""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import MemorySaver

from strategy_navigator.graph.state import initial_state
from strategy_navigator.stages.rapid_consolidation import build


@pytest.fixture
def graph():
    return build().compile(checkpointer=MemorySaver())


async def test_rapid_consolidation_chains_calls_and_maps_agent_ids(
    graph, fake_structured, sample_project
):
    fake_structured.set(
        "revise_existing",
        {
            "ideas": [
                {
                    "title": "Idea A",
                    "summary": "Revised idea A.",
                    "sources": [],
                    "categories": ["Grid"],
                    "provenance": "revised-existing",
                    "tier": "Lead",
                }
            ]
        },
    )
    fake_structured.set(
        "consolidate_documents",
        {
            "documentHighlights": [
                {"document": "doc1.pdf", "summary": "Good doc.", "keyInsights": ["insight"]}
            ],
            "ideaCandidates": [],
        },
    )
    fake_structured.set(
        "surface_new_ideas",
        {
            "ideas": [
                {
                    "title": "Idea B (new)",
                    "summary": "A brand new idea.",
                    "sources": [],
                    "categories": ["Grid"],
                    "provenance": "new",
                    "tier": "Contender",
                }
            ]
        },
    )

    state = initial_state(
        run_id="rapid_consolidation:s1",
        session_id="s1",
        workflow="rapid_consolidation",
        project_id=42,
        request={
            "sessionId": "s1",
            "project": sample_project,
            "consolidationType": "human",
            "agents": [
                {
                    "id": 1,
                    "name": "Grid Economist",
                    "agentType": "foundational",
                    "isDomainSpecific": False,
                    "ideas": [
                        {
                            "title": "Idea A",
                            "summary": "Original idea A.",
                            "type": "strategic",
                            "comments": ["make it faster"],
                        }
                    ],
                },
                {
                    "id": 2,
                    "name": "Ideators",
                    "agentType": "human",
                    "isDomainSpecific": False,
                    "ideas": [
                        {
                            "title": "Idea B (new)",
                            "summary": "A brand new idea.",
                            "type": "human",
                        }
                    ],
                },
            ],
            "documentComments": [{"documentKey": "doc1.pdf", "comments": ["good doc"]}],
        },
    )
    config = {"configurable": {"thread_id": "rapid_consolidation:s1"}}
    final = await graph.ainvoke(state, config)

    assert final["artifacts"]["revised_existing_ideas"][0]["title"] == "Idea A"
    assert final["artifacts"]["document_commentary"]["idea_candidates"] == []

    result = final["result"]
    assert result["sessionId"] == "s1"
    assert result["consolidationType"] == "human"
    ideas = {i["title"]: i for i in result["ideas"]}
    assert ideas["Idea A"]["agentId"] == 1
    assert ideas["Idea A"]["isDomainSpecificAgent"] is False
    assert ideas["Idea B (new)"]["agentId"] == 2
