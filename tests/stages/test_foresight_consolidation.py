"""foresight_consolidation graph, compiled with an in-memory checkpointer."""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import MemorySaver

from strategy_navigator.graph.state import initial_state
from strategy_navigator.stages.foresight_consolidation import build


@pytest.fixture
def graph():
    return build().compile(checkpointer=MemorySaver())


async def test_foresight_consolidation_flattens_and_consolidates(
    graph, fake_structured, sample_project
):
    fake_structured.set(
        "consolidate",
        {
            "ideas": [
                {
                    "title": "Grid-edge sensing rollout",
                    "summary": "Deploy edge sensors across substations. Tension: cost vs speed.",
                    "sources": [],
                    "categories": ["Grid Modernisation"],
                    "sourceAgents": ["foundational:1", "domain:2"],
                    "tier": "Lead",
                    "horizon": "NEAR",
                }
            ]
        },
    )
    state = initial_state(
        run_id="foresight_consolidation:s1",
        session_id="s1",
        workflow="foresight_consolidation",
        project_id=42,
        request={
            "sessionId": "s1",
            "project": sample_project,
            "solutions": [
                {
                    "sourceAgent": "foundational:1",
                    "agentName": "Grid Economist",
                    "agentType": "foundational",
                    "isDomainSpecific": False,
                    "opportunities": [
                        {
                            "title": "Grid-edge sensing rollout",
                            "horizon": "NEAR",
                            "importance": "Reduces outage detection time.",
                            "target_audience": "Operations",
                            "success": "50% faster fault detection.",
                            "cost": "Medium",
                            "opportunity_rationale": "Holds across all scenarios.",
                        }
                    ],
                },
                {
                    "sourceAgent": "domain:2",
                    "agentName": "Ops Reliability Lead",
                    "agentType": "contextual",
                    "isDomainSpecific": True,
                    "opportunities": [],
                },
            ],
        },
    )
    config = {"configurable": {"thread_id": "foresight_consolidation:s1"}}
    final = await graph.ainvoke(state, config)

    assert final["artifacts"]["initiatives"] == [
        {
            "title": "Grid-edge sensing rollout",
            "horizon": "NEAR",
            "importance": "Reduces outage detection time.",
            "target_audience": "Operations",
            "success": "50% faster fault detection.",
            "cost": "Medium",
            "opportunity_rationale": "Holds across all scenarios.",
            "source_agent": "foundational:1",
        }
    ]
    result = final["result"]
    assert result["sessionId"] == "s1"
    assert result["ideas"][0]["tier"] == "Lead"
    assert result["ideas"][0]["sourceAgents"] == ["foundational:1", "domain:2"]
