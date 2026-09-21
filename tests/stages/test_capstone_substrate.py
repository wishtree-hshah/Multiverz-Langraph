"""capstone_substrate graph, end to end, compiled with an in-memory
checkpointer (no Postgres)."""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import MemorySaver

from strategy_navigator.graph.state import initial_state
from strategy_navigator.stages.capstone_substrate import build


@pytest.fixture
def graph():
    return build().compile(checkpointer=MemorySaver())


def _request() -> dict:
    ten_step_input = {
        "sessionId": "r-1",
        "projectId": 42,
        "project": {
            "clientOrganization": "NorthGrid",
            "clientContext": "Regulated utility.",
            "projectName": "Grid Modernisation",
        },
        "metrics": {
            "solutionContributorsCount": 1,
            "humanIdeatorCount": 1,
            "agentContributorCount": 1,
        },
        "solutions": [
            {
                "agentInfo": {
                    "agentId": 1,
                    "agentName": "Agent One",
                    "agentDesignation": "Regulator",
                },
                "10StepForm": {
                    "weakSignals": [
                        {
                            "id": "ws1",
                            "title": "Grid modernization signal",
                            "type": "Weak Signal",
                            "domain": "Energy",
                            "impact": 4,
                            "uncertainty": 3,
                            "probability": 0.6,
                            "timeRange": "<2",
                            "description": "Grid demand grew 12 percent last year.",
                            "implications": "Requires new substations.",
                            "relatedWeakSignals": "",
                            "solutionReferences": {
                                "citations": "",
                                "referenceUrls": ["https://example.com/grid-report"],
                                "referenceDocuments": [],
                            },
                        }
                    ],
                    "bestPractices": [
                        {
                            "id": "bp1",
                            "title": "Sensor rollout in peer utility",
                            "organizationName": "PeerCo",
                            "challenge": "Aging grid infrastructure.",
                            "solutionText": "Deployed edge sensors across substations.",
                            "outcome": "Fault detection improved.",
                            "implementation": "Phased rollout over 2 years.",
                            "tags": [],
                        }
                    ],
                    "solutionFrameworks": [],
                    "quickLongTermStrategies": "Modernise the grid.",
                    "solutionOpportunities": [
                        {
                            "termActionables": [
                                {
                                    "title": "Deploy sensors",
                                    "highImpactInitiatives": [
                                        {
                                            "initiativeId": "INIT1",
                                            "termType": "near",
                                            "actionableImportance": "high",
                                            "successLooksLike": "Faster fault detection.",
                                            "associatedCost": "Medium",
                                        }
                                    ],
                                }
                            ]
                        }
                    ],
                    "step10": {
                        "the_preferred_future": "By 2030 the grid self-heals.",
                        "three_uncomfortable_conclusions": "Manual dispatch is already obsolete.",
                        "strategic_options_and_robustness": "Invest in sensors now.",
                        "action_pathways": "Pilot then scale.",
                        "implications_across_three_horizons": "Near-term pilots, long-term automation.",
                        "indicators_to_monitor": "Outage frequency.",
                        "stakeholder_context": "Regulator wants reliability.",
                        "signals_and_drivers_relevant_to_this_stakeholder": "Grid modernization signal.",
                        "strategic_scenarios_stakeholder_specific_reading": "Automation scenario.",
                        "critical_uncertainties_through_this_stakeholders_lens": "Funding availability.",
                    },
                },
            }
        ],
    }
    ideas_input = {
        "projectIdeas": [
            {
                "id": 100,
                "title": "Community sensor idea",
                "summary": "Install sensors at key points.",
                "categories": [],
                "sources": [],
                "overallScore": 4,
                "humanScore": 4,
                "agentScore": 4,
                "ratings": [{"voterType": "Human", "voterName": "V1", "score": 4}],
            }
        ],
        "solutions": [
            {
                "agentInfo": {"agentId": 1, "agentName": "Agent One", "agentType": "foundational"},
                "solutionIdeas": [
                    {
                        "id": 200,
                        "title": "Sensor rollout idea",
                        "summary": "Deploy sensors per initiative.",
                        "categories": [],
                        "sources": [],
                        "templateId": None,
                        "overallScore": 3,
                        "humanScore": 3,
                        "agentScore": 3,
                        "ratings": [],
                    }
                ],
            }
        ],
    }
    return {
        "sessionId": "r-1",
        "projectId": 42,
        "triggerBatchId": "batch-1",
        "tenStepInput": ten_step_input,
        "ideasInput": ideas_input,
    }


def _script(fake_structured) -> None:
    fake_structured.set(
        "facts_register",
        {
            "facts": [
                {
                    "factId": "F001",
                    "statement": "Grid demand grew 12 percent last year.",
                    "value": "12",
                    "unit": "percent",
                    "asOf": "2025",
                    "citationKeys": [],
                    "uncited": True,
                    "sourceAgents": [1],
                }
            ]
        },
    )
    fake_structured.set(
        "entity_signals",
        {
            "sigDecisions": [
                {
                    "signalId": "SIG001",
                    "memberOriginalIds": ["ws1"],
                    "title": "Grid modernization signal",
                    "domain": "Energy",
                    "descriptionFrom": "ws1",
                    "implicationsFrom": "ws1",
                    "impact": 4,
                    "uncertainty": 3,
                    "probability": 0.6,
                    "horizon": "<2",
                }
            ]
        },
    )
    fake_structured.set("entity_uncertainties", {"uncDecisions": []})
    fake_structured.set(
        "entity_best_practices",
        {
            "bpDecisions": [
                {
                    "bestPracticeId": "BP001",
                    "memberOriginalIds": ["bp1"],
                    "titleFrom": "bp1",
                    "challengeFrom": "bp1",
                    "solutionTextFrom": "bp1",
                    "outcomeFrom": "bp1",
                    "implementationFrom": "bp1",
                }
            ]
        },
    )
    fake_structured.set(
        "action_map",
        {
            "validationPresent": True,
            "ideaToInitiative": [
                {
                    "ideaId": 200,
                    "track": "solutionExtracted",
                    "agentId": 1,
                    "candidateInitiativeId": "INIT1",
                    "associationConfidence": "high",
                    "associationBasis": "templateId",
                },
                {
                    "ideaId": 100,
                    "track": "rapid",
                    "agentId": None,
                    "candidateInitiativeId": None,
                    "associationConfidence": "none",
                    "associationBasis": "",
                },
            ],
        },
    )
    fake_structured.set(
        "relational_binding",
        {
            "uncertaintyBindings": [],
            "signalBindings": [
                {
                    "signalId": "SIG001",
                    "becameScenarioAxis": False,
                    "axisRefs": [],
                    "resolutionNotes": "",
                }
            ],
            "scenarioBindings": [],
        },
    )
    fake_structured.set(
        "trend_clustering",
        {
            "trends": [
                {
                    "trendId": "TRD001",
                    "label": "Grid modernization trend",
                    "memberSignalIds": ["SIG001"],
                    "sourceAgents": [1],
                    "convergence": 1,
                    "impact": 4,
                    "uncertainty": 3,
                    "horizon": "<2",
                    "confidence": "medium",
                    "trajectoryBasis": "Direction inferred from cross-contributor convergence.",
                    "becameScenarioAxis": False,
                    "axisRefs": [],
                }
            ]
        },
    )
    fake_structured.set(
        "recommendations",
        {
            "settledRecommendations": [
                {
                    "recommendationId": "REC001",
                    "statement": "Deploy grid sensors.",
                    "rationale": "Improves fault detection.",
                    "horizon": "<2",
                    "supportingSignalIds": ["SIG001"],
                    "supportingBestPracticeIds": ["BP001"],
                    "sourceAgents": [1],
                    "linkedIdeaIds": [200],
                    "citationKeys": [],
                    "suggestedOwner": "Grid Operator",
                    "dependencies": [],
                    "sequenceRank": 1,
                }
            ],
            "minorityPositions": [],
        },
    )
    fake_structured.set(
        "stakeholder_lensing",
        {
            "stakeholderLensMap": [
                {
                    "stakeholder": "Regulator",
                    "relevantSignalIds": ["SIG001"],
                    "relevantUncertaintyIds": [],
                    "relevantRecommendationIds": ["REC001"],
                    "lensNotes": "Cares about reliability.",
                }
            ]
        },
    )
    fake_structured.set(
        "preferred_future",
        {
            "preferredFuture": {
                "preferredFutureId": "PF001",
                "statement": "By 2030 the grid self-heals across every substation.",
                "horizonYear": "2030",
                "gapFromMostLikely": "The most likely future keeps manual dispatch; this future automates it.",
                "distinguishingFeatures": [
                    {
                        "feature": "Automated dispatch",
                        "supportingSignalIds": ["SIG001"],
                        "factIds": ["F001"],
                    }
                ],
                "falsificationIndicator": "No pilot funded by 2027.",
                "sourceAgents": [1],
                "stakeholderEmphases": [],
                "citationKeys": [],
            },
            "provocations": [
                {
                    "provocationId": "PRV001",
                    "claim": "Manual dispatch is already obsolete.",
                    "contradicts": "Utilities believe manual dispatch is safe.",
                    "supportingIds": ["SIG001"],
                    "ifTrue": "Utilities must invest now.",
                    "sourceAgents": [1],
                    "citationKeys": [],
                }
            ],
        },
    )
    fake_structured.set(
        "investment_sizing",
        {
            "investmentEnvelopes": [
                {
                    "recommendationId": "REC001",
                    "label": "Sensor rollout",
                    "capexRange": {"low": 1000000, "high": 5000000, "currency": "USD", "note": ""},
                    "opexAnnualRange": {
                        "low": 100000,
                        "high": 300000,
                        "currency": "USD",
                        "note": "",
                    },
                    "phasing": [{"horizon": "<2", "description": "Pilot", "shareOfCapex": "30%"}],
                    "basis": "analyst-estimate",
                    "anchorFactIds": [],
                    "comparables": [],
                    "assumptions": ["Scope: 50 substations"],
                    "confidence": "low",
                    "indicative": True,
                    "citationKeys": [],
                    "unresolved": False,
                    "unresolvedReason": "",
                }
            ],
            "newSources": [],
        },
    )
    fake_structured.set(
        "substrate_review",
        {
            "verdict": "pass",
            "findings": [],
            "passedChecks": ["contradiction", "horizon_balance"],
            "summaryJudgement": "Substrate is sound enough to build on.",
        },
    )


async def test_capstone_substrate_end_to_end(graph, fake_structured, fake_search):
    _script(fake_structured)

    state = initial_state(
        run_id="capstone_substrate:r-1",
        session_id="r-1",
        workflow="capstone_substrate",
        project_id=42,
        request=_request(),
    )
    config = {"configurable": {"thread_id": "capstone_substrate:r-1"}}
    final = await graph.ainvoke(state, config)

    substrate = final["artifacts"]["assembly"]["substrate"]

    # citation resolution: the URL fragment on ws1 became a real source, no LLM needed.
    assert substrate["citations"]["sources"][0]["sourceId"] == "S001"
    assert substrate["citations"]["sources"][0]["url"] == "https://example.com/grid-report"

    # fact repair: F001's "12" matches SIG001's description, so citationKeys got attached
    # and uncited flipped false via the number-matching heuristic (Node 11 port).
    fact = substrate["facts"][0]
    assert fact["uncited"] is False
    assert "S001" in fact["citationKeys"]

    # entity consolidation reconstruction
    assert substrate["signals"][0]["signalId"] == "SIG001"
    assert substrate["bestPractices"][0]["bestPracticeId"] == "BP001"

    # divergence: single human rater reconciles exactly -> full fidelity
    assert substrate["divergence"]["fidelity"] == "full"

    # investment rollup: id assigned deterministically, never by the LLM
    envelope = substrate["investmentEnvelopes"][0]
    assert envelope["investmentId"] == "INV001"
    assert substrate["investmentSummary"]["totalCapexRange"] == {
        "low": 1000000,
        "high": 5000000,
        "currency": "USD",
    }

    # deliberate fix: substrate review verdict attached to the substrate itself
    assert substrate["review"]["verdict"] == "pass"

    result = final["result"]
    assert result["triggerBatchId"] == "batch-1"
    assert result["status"] == "completed"
    assert result["substrate"]["settledRecommendations"][0]["recommendationId"] == "REC001"
