"""custom_archetype graph, compiled with an in-memory checkpointer (no Postgres)."""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import MemorySaver

from strategy_navigator.graph.state import initial_state
from strategy_navigator.stages.custom_archetype import build


@pytest.fixture
def graph():
    return build().compile(checkpointer=MemorySaver())


async def test_custom_archetype_produces_callback(graph, fake_structured, sample_project):
    fake_structured.set(
        "generate_archetype",
        {
            "archetype": {
                "name": "Board Risk Brief",
                "primaryReader": "Board of Directors",
                "template": "Brief",
                "intendedUse": "read",
                "externalOptionsProminence": "note",
                "divergenceDisplay": "summary",
                "typicalPages": 8,
                "sectionList": ["Recommendation", "Key Risks", "Methodology"],
                "bodyIsCountDriven": False,
            },
            "provenance": [
                {"field": "template", "source": "recommended", "reason": "Short decision doc."},
            ],
            "needsConfirmation": True,
        },
    )
    state = initial_state(
        run_id="custom_archetype:s1",
        session_id="s1",
        workflow="custom_archetype",
        project_id=42,
        request={
            "sessionId": "s1",
            "project": sample_project,
            "spec": {
                "name": "Board Risk Brief",
                "purpose": "Brief the board on regulatory risk",
                "primaryReader": "Board of Directors",
                "pages": 8,
                "intendedUse": "read",
            },
        },
    )
    config = {"configurable": {"thread_id": "custom_archetype:s1"}}
    final = await graph.ainvoke(state, config)

    result = final["result"]
    assert result["sessionId"] == "s1"
    assert result["status"] == "assembled"
    assert result["archetype"]["name"] == "Board Risk Brief"
    assert result["archetype"]["sectionList"] == ["Recommendation", "Key Risks", "Methodology"]
    assert result["provenance"][0]["field"] == "template"
