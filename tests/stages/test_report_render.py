"""report_render graph: the SHIP (no findings) and HOLD (revision-cycle) paths,
compiled with an in-memory checkpointer."""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import MemorySaver

from strategy_navigator.graph.state import initial_state
from strategy_navigator.stages.report_render import build


@pytest.fixture
def graph():
    return build().compile(checkpointer=MemorySaver())


def _request(sample_project: dict) -> dict:
    return {
        "sessionId": "r-1",
        "renderBatchId": "rb-1",
        "project": sample_project,
        "substrate": {
            "facts": [{"factId": "F001", "value": "12%", "citationKeys": ["S001"]}],
            "citations": {
                "sources": [{"sourceId": "S001", "footnoteText": "Regulator filing", "url": None}]
            },
        },
        "selectedArchetypes": [{"archetypeKey": "decision-brief", "requestedPages": 5}],
    }


_GAPS = {
    "namedGaps": [
        {
            "gapId": "GAP001",
            "description": "No cost benchmark",
            "whyItMatters": "Board will ask",
            "searchable": True,
        }
    ]
}
_EXTERNAL = {"externalOptions": [], "existenceProofs": []}
_RENDER_PLAN = {
    "renderPlan": {
        "totalWordBudget": 2250,
        "primaryReader": "Board",
        "intendedUse": "read",
        "externalOptionsProminence": "note",
        "divergenceDisplay": "summary",
        "searchBudget": 3,
        "planningNotes": "",
        "sections": [
            {
                "sectionName": "Executive Summary",
                "wordTarget": 500,
                "toleranceBand": [450, 550],
                "emphasis": "primary",
                "sectionRule": "",
            }
        ],
    }
}
_FACT_CURRENCY = {"factCurrencyQueries": []}
_SECTION_CONTENT = " ".join(["Ridership fell 12% (S001)."] * 30)
_SECTIONS = {
    "sections": [
        {
            "sectionName": "Executive Summary",
            "content": _SECTION_CONTENT,
            "citationKeysUsed": ["S001"],
            "factIdsUsed": ["F001"],
            "externalOptionIdsUsed": [],
            "unfillable": False,
            "wordCount": 120,
        }
    ]
}
_EDITED_SECTION = _SECTIONS["sections"][0]
_QC3 = {
    "critic": "reader_persona_panel",
    "readers": [{"reader": "decision_maker", "decisionEnabled": "Approve the tariff change"}],
    "convergentIssues": [],
    "summaryJudgement": "Survives its first meeting.",
}
_QC4 = {
    "critic": "red_team",
    "findings": [],
    "survivedAttacks": [],
    "strongestCounterargument": "A rival advisor could argue the timeline is too aggressive.",
    "summaryJudgement": "Central argument holds.",
}
_QC5 = {
    "critic": "surprise_genericity_scorer",
    "sectionVerdicts": [
        {
            "sectionName": "Executive Summary",
            "verdict": "specific",
            "evidence": "Ridership fell (S001).",
        }
    ],
    "mostGenericParagraphs": [],
    "mostInsightDense": [],
    "truismCheck": [],
    "nonObviousClaims": [],
    "surpriseVerdict": {
        "score": "adequate",
        "cause": "substrate",
        "reasoning": "One non-obvious claim.",
    },
    "protectionList": [],
    "summaryJudgement": "Adequately specific.",
}


def _script_common(fake_structured, fake_search, sample_project) -> None:
    fake_structured.set("detect_gaps", _GAPS)
    fake_structured.set("search_external", _EXTERNAL)
    fake_structured.set("plan_render", _RENDER_PLAN)
    fake_structured.set("plan_fact_currency", _FACT_CURRENCY)
    fake_structured.set("generate_sections", _SECTIONS)
    fake_structured.set("edit_sections", _EDITED_SECTION)
    fake_structured.set("qc3", _QC3)
    fake_structured.set("qc4", _QC4)
    fake_structured.set("qc5", _QC5)


async def test_report_render_ship_path_skips_revision(
    graph, fake_structured, fake_search, sample_project
):
    _script_common(fake_structured, fake_search, sample_project)
    fake_structured.set(
        "qc1",
        {
            "critic": "traceability_auditor",
            "findings": [],
            "cleanSections": ["Executive Summary"],
            "summaryJudgement": "Clean.",
        },
    )
    fake_structured.set(
        "qc2",
        {
            "critic": "coherence_checker",
            "findings": [],
            "passedChecks": [],
            "summaryJudgement": "Coherent.",
        },
    )
    fake_structured.set(
        "qc_c1",
        {
            "critic": "render_conformance",
            "findings": [],
            "passedChecks": [],
            "summaryJudgement": "Conforms.",
        },
    )
    fake_structured.set(
        "score_and_gate",
        {
            "gate": "SHIP",
            "gateReasoning": "No open findings.",
            "openFindings": {"blocker": [], "major": [], "minor": []},
            "disagreements": [],
            "sectionCompleteness": {"blockers": [], "honestGaps": []},
            "surpriseAndAmbition": {
                "score": "adequate",
                "reason": "One non-obvious claim.",
                "nonObviousClaims": [],
            },
            "certifiedStrengths": [],
            "strongestCounterargument": "",
            "humanReviewPriorities": [],
            "scorecard_markdown": "# Scorecard\nSHIP.",
        },
    )

    state = initial_state(
        run_id="report_render:r-1",
        session_id="r-1",
        workflow="report_render",
        project_id=42,
        request=_request(sample_project),
    )
    final = await graph.ainvoke(state, {"configurable": {"thread_id": "report_render:r-1"}})

    assert "revision" not in final["artifacts"]
    assert final["artifacts"]["qcConsolidated"]["cycleCount"] == 0

    result = final["result"]
    assert result["renderBatchId"] == "rb-1"
    assert result["status"] == "completed"
    report = result["reports"][0]
    assert report["qcGate"] == "SHIP"
    assert "## Executive Summary" in report["content"]
    assert "[1]" in report["content"]
    assert "## References" in report["content"]
    assert report["citationCount"] == 1


async def test_report_render_hold_path_runs_revision_and_recheck(
    graph, fake_structured, fake_search, sample_project
):
    _script_common(fake_structured, fake_search, sample_project)
    fake_structured.set(
        "qc1",
        {
            "critic": "traceability_auditor",
            "findings": [
                {
                    "findingId": "TRC001",
                    "sectionName": "Executive Summary",
                    "category": "UNCITED_LOAD_BEARING",
                    "severity": "major",
                    "quote": "Ridership fell",
                    "checkedAgainst": "",
                    "issue": "Uncited claim.",
                    "suggestedFix": "cite F001",
                }
            ],
            "cleanSections": [],
            "summaryJudgement": "One uncited claim.",
        },
    )
    fake_structured.set(
        "qc2",
        {
            "critic": "coherence_checker",
            "findings": [],
            "passedChecks": [],
            "summaryJudgement": "Coherent.",
        },
    )
    fake_structured.set(
        "qc_c1",
        {
            "critic": "render_conformance",
            "findings": [],
            "passedChecks": [],
            "summaryJudgement": "Conforms.",
        },
    )
    fake_structured.set(
        "revise_report",
        {
            "revised_sections": [
                {**_EDITED_SECTION, "content": _SECTION_CONTENT + " Cited now (S001)."},
            ],
            "change_log": [
                {
                    "findingId": "TRC001",
                    "sectionName": "Executive Summary",
                    "action": "corrected",
                    "before": "Ridership fell",
                    "after": "Ridership fell (S001)",
                    "note": "",
                }
            ],
            "unresolved": [],
        },
    )
    fake_structured.set(
        "qc1_recheck",
        {
            "critic": "traceability_auditor",
            "findings": [],
            "cleanSections": ["Executive Summary"],
            "summaryJudgement": "Fixed.",
        },
    )
    fake_structured.set(
        "qc2_recheck",
        {
            "critic": "coherence_checker",
            "findings": [],
            "passedChecks": [],
            "summaryJudgement": "Coherent.",
        },
    )
    fake_structured.set(
        "qc_c1_recheck",
        {
            "critic": "render_conformance",
            "findings": [],
            "passedChecks": [],
            "summaryJudgement": "Conforms.",
        },
    )
    fake_structured.set(
        "score_and_gate",
        {
            "gate": "SHIP_WITH_NOTES",
            "gateReasoning": "Revision resolved the only major finding.",
            "openFindings": {"blocker": [], "major": [], "minor": []},
            "disagreements": [],
            "sectionCompleteness": {"blockers": [], "honestGaps": []},
            "surpriseAndAmbition": {
                "score": "adequate",
                "reason": "One non-obvious claim.",
                "nonObviousClaims": [],
            },
            "certifiedStrengths": [],
            "strongestCounterargument": "",
            "humanReviewPriorities": ["Confirm the citation fix."],
            "scorecard_markdown": "# Scorecard\nSHIP_WITH_NOTES.",
        },
    )

    state = initial_state(
        run_id="report_render:r-2",
        session_id="r-2",
        workflow="report_render",
        project_id=42,
        request=_request(sample_project),
    )
    final = await graph.ainvoke(state, {"configurable": {"thread_id": "report_render:r-2"}})

    assert final["artifacts"]["qcFirstPass"]["hasBlockerOrMajor"] is True
    assert final["artifacts"]["qcConsolidated"]["cycleCount"] == 1
    assert final["artifacts"]["revision"]["changeLog"][0]["findingId"] == "TRC001"

    result = final["result"]
    report = result["reports"][0]
    assert report["qcGate"] == "SHIP_WITH_NOTES"
    assert "Cited now" in report["content"]
