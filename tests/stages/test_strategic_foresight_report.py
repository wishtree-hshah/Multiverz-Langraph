"""strategic_foresight_report graph: single structured call against the
recovered "Report Generation" prompt (id 6) -> callback with the report under
``output``."""

from __future__ import annotations

from typing import Any

import pytest
from langgraph.checkpoint.memory import MemorySaver

from strategy_navigator.graph.state import initial_state
from strategy_navigator.stages.strategic_foresight_report import build


@pytest.fixture
def graph():
    return build().compile(checkpointer=MemorySaver())


def _request() -> dict:
    return {
        "sessionId": "fr-1",
        "projectId": 42,
        "triggerBatchId": "batch-1",
        "project": {
            "projectId": 42,
            "projectName": "Grid Modernisation",
            "projectDescription": "Regional utility upgrading its distribution grid.",
            "clientOrganization": "NorthGrid",
            "clientContext": "Regulated utility, 2.1M customers.",
            "reportProfileForClient": "Board-level strategy brief",
            "timeLines": "18 months",
            "projectIntent": None,
            "stakeholders": ["Regulator"],
            "documents": [],
        },
        "ideationProcess": {
            "foundationalAgents": {"count": 3},
            "contextualAgents": {"count": 2},
            "humanIdeators": {"count": 1},
        },
        "projectIdeas": [],
        "solutions": [{"agentInfo": {"agentId": 1, "agentName": "A", "agentType": "Domain"}}],
        "metrics": {
            "solutionIdeasCount": 4,
            "solutionContributorsCount": 3,
            "foundationalAgentsCount": 3,
            "contextualAgentsCount": 2,
            "humanIdeatorsCount": 1,
        },
    }


def _report_output() -> dict[str, Any]:
    return {
        "executiveBrief": {
            "openingParagraph": "o",
            "top5Priorities": [
                {
                    "title": "Grid telemetry rollout",
                    "score": "4.2 / 5.0",
                    "description": "d",
                    "strategicSignificance": "s",
                }
            ],
            "methodologyNote": "m",
            "quickWins": [{"action": "a", "expectedOutcome": "e"}],
            "closing": "c",
        },
        "part1ProcessAndParticipation": {
            "methodology": "m",
            "participationOverview": "p",
            "participationFlowTable": "t",
            "evaluationFrameworkTable": [
                {"criterionName": "Impact", "description": "d", "weightPercent": "30%"}
            ],
            "evaluationFrameworkParagraphs": "p",
            "qualityAssurance": "q",
        },
        "part2FindingsAndAnalysis": {
            "portfolioOverview": "o",
            "analysisByCategory": [
                {
                    "categoryName": "Grid resilience",
                    "ideaCount": 4,
                    "topScore": "4.2 / 5.0",
                    "analysis": "a",
                    "convergencePoints": [],
                    "divergencePoints": [],
                }
            ],
            "aiHumanAlignment": "a",
            "crossCategorySynthesis": "c",
        },
        "part3ScenarioTesting": {
            "overview": "o",
            "scenarios": [
                {
                    "scenarioName": "High-growth",
                    "description": "d",
                    "robustnessMatrix": [],
                    "insights": "i",
                }
            ],
        },
        "part4StrategicActionPlan": {
            "prioritiesTable": [
                {
                    "rank": 1,
                    "ideaTitle": "Grid telemetry rollout",
                    "score": "4.2 / 5.0",
                    "owner": "Ops",
                    "timeline": "Q1",
                }
            ],
            "sequencingRationale": "r",
            "timelineTable": "t",
            "actionCards": [
                {
                    "actionId": "A1",
                    "actionTitle": "Deploy telemetry",
                    "owner": "Ops",
                    "startMonth": 1,
                    "endMonth": 3,
                    "resourceBudget": "b",
                    "description": "d",
                    "keyRisks": "r",
                }
            ],
            "quickWins": [{"action": "a", "expected30DayOutcome": "e"}],
            "monitoringTable": [
                {
                    "metricName": "Uptime",
                    "baseline": "97%",
                    "target": "99.5%",
                    "frequency": "Monthly",
                    "owner": "Ops",
                }
            ],
            "adaptationTriggers": "t",
        },
        "part5KnowledgeGaps": {
            "overview": "o",
            "gaps": [
                {
                    "gapTitle": "Load forecasting",
                    "currentState": "c",
                    "whyItMatters": "w",
                    "recommendedResearch": "r",
                    "estimatedEffort": "e",
                }
            ],
        },
        "annexes": {
            "completeIdeaInventory": [
                {
                    "id": "1",
                    "title": "Grid telemetry rollout",
                    "category": "Grid resilience",
                    "score": "4.2 / 5.0",
                    "source": "Domain agent",
                    "timeline": "Q1",
                }
            ],
            "evaluationDataSummary": "s",
            "scenarioMatrices": "m",
        },
    }


async def test_strategic_foresight_report_generates_and_assembles(graph, fake_structured):
    fake_structured.set("generate_report", _report_output())

    state = initial_state(
        run_id="strategic_foresight_report:fr-1",
        session_id="fr-1",
        workflow="strategic_foresight_report",
        project_id=42,
        request=_request(),
    )
    config = {"configurable": {"thread_id": "strategic_foresight_report:fr-1"}}
    final = await graph.ainvoke(state, config)

    counters = final["artifacts"]["counters"]
    assert counters["agent_count"] == 5
    assert counters["human_count"] == 1
    assert counters["solution_ideas_count"] == 4

    result = final["result"]
    assert result["sessionId"] == "fr-1"
    assert result["projectId"] == 42
    assert result["output"]["executiveBrief"]["closing"] == "c"
    assert result["output"]["part4StrategicActionPlan"]["actionCards"][0]["actionId"] == "A1"
