"""strategy_form_idea_generation graph: fan-out one Send per template, reusing
IdeaExtractionOutput for the LLM call and PipelineState["partials"] to
collect rows into the ``{"results": [...]}`` callback body."""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import MemorySaver

from strategy_navigator.graph.state import initial_state
from strategy_navigator.stages.strategy_form_idea_generation import build


@pytest.fixture
def graph():
    return build().compile(checkpointer=MemorySaver())


def _request() -> dict:
    return {
        "sessionId": "run-abc",
        "projectId": 42,
        "templates": [
            {
                "templateId": 101,
                "projectId": 42,
                "projectName": "Grid Modernisation",
                "projectDescription": "Regional utility upgrading its distribution grid.",
                "templateSolution": {"executiveSummary": "Deploy smart meters region-wide."},
            },
            {
                "templateId": 102,
                "projectId": 42,
                "projectName": "Grid Modernisation",
                "projectDescription": "Regional utility upgrading its distribution grid.",
                "templateSolution": {"executiveSummary": "Islanded microgrids for substations."},
            },
        ],
        "usermetadata": {"id": 7, "firstName": "Jamie", "lastName": "Lee", "email": "j@x.com"},
    }


def _idea_output() -> dict:
    return {
        "ideas": [
            {
                "title": "Region-wide smart meter rollout",
                "summary": "Deploys AMI meters to cut outage detection time.",
                "categories": ["Grid resilience"],
                "sources": ["10-step form solution: executiveSummary"],
            }
        ]
    }


async def test_strategy_form_idea_generation_fans_out_and_aggregates(
    graph, fake_structured, fake_search
):
    fake_structured.set("score_template", _idea_output())

    state = initial_state(
        run_id="strategy_form_idea_generation:run-abc",
        session_id="run-abc",
        workflow="strategy_form_idea_generation",
        project_id=42,
        request=_request(),
    )
    config = {"configurable": {"thread_id": "strategy_form_idea_generation:run-abc"}}
    final = await graph.ainvoke(state, config)

    result = final["result"]
    rows = result["results"]
    assert len(rows) == 2
    assert {r["templateId"] for r in rows} == {101, 102}
    # runId echoes the raw backend UUID (sessionId), not our internal composite run_id.
    assert all(r["runId"] == "run-abc" for r in rows)
    assert all(r["user"]["id"] == 7 for r in rows)
    assert all(r["project"]["id"] == 42 for r in rows)
    assert all(r["results"][0]["title"] == "Region-wide smart meter rollout" for r in rows)
