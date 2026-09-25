"""form_filling_10step graph: the 9 human-approval gates, checkpoint delivery,
and the SHIP-path QC panel on step 10 — compiled with an in-memory
checkpointer."""

from __future__ import annotations

from typing import Any

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from strategy_navigator.graph.state import initial_state
from strategy_navigator.stages.form_filling_10step import build


@pytest.fixture
def graph():
    return build().compile(checkpointer=MemorySaver())


@pytest.fixture
def fake_checkpoints(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def _post_callback(**kw: Any) -> None:
        calls.append(kw)

    monkeypatch.setattr(
        "strategy_navigator.stages.form_filling_10step.post_callback", _post_callback
    )
    return calls


def _request() -> dict:
    return {
        "sessionId": "ff-1",
        "project": {
            "projectId": 42,
            "projectName": "Grid Modernisation",
            "projectDescription": "Regional utility upgrading its distribution grid.",
            "clientOrganization": "NorthGrid",
            "clientContext": "Regulated utility, 2.1M customers.",
            "reportProfileForClient": "Board-level strategy brief",
            "stakeholders": ["Regulator"],
            "documents": [],
        },
        "agent": {
            "id": 7,
            "name": "Grid Economist",
            "designation": "Economist",
            "description": "Analyse grid economics.",
        },
    }


def _step_output(n: int) -> dict[str, Any]:
    if n == 1:
        return {
            "defineProblem": "p",
            "problemBreakdown": "b",
            "infoAssessment": "i",
            "solutionExplorationInnovation": "e",
            "solutionImplementation": "s",
            "problemChallengeSynthesis": "y",
        }
    if n == 2:
        return {"bestPractices": [], "solutionReferences": {}, "nextPractices": "n"}
    if n == 3:
        return {"weakSignals": [], "uncertainties": [], "driversOfChange": "d"}
    if n == 4:
        return {
            "0": {"scenarioA": "a"},
            "1": None,
            "preferredFuture": "pf",
            "solutionReferences": {},
        }
    if n == 5:
        return {
            "keyInsights": "k",
            "opportunitySpaces": "o",
            "riskResilience": "r",
            "innovationPathways": "i",
            "quickLongTermStrategies": "q",
            "solutionReferences": {},
        }
    if n == 6:
        return {"solutionTermOpportunities": [], "solutionReferences": {}}
    if n == 7:
        return {"highPriorityTermActionable": [], "solutionReferences": {}}
    if n == 8:
        return {"immediateActions": [], "solutionReferences": {}}
    if n == 9:
        return {
            "solution": {"executiveSummary": "e", "futurePressRelease": "f"},
            "solutionReferences": {},
        }
    return {
        "masthead": "m",
        "executive_summary": "This section says something specific about NorthGrid.",
        "key_figures": "k",
        "three_uncomfortable_conclusions": "t",
        "stakeholder_context": "s",
        "methodology_note": "n",
        "signals_and_drivers_relevant_to_this_stakeholder": "sd",
        "critical_uncertainties_through_this_stakeholders_lens": "cu",
        "strategic_scenarios_stakeholder_specific_reading": "ss",
        "the_preferred_future": "pf",
        "implications_across_three_horizons": "ih",
        "strategic_options_and_robustness": "so",
        "indicators_to_monitor": "im",
        "action_pathways": "ap",
        "annexes": "an",
        "references": "r",
    }


def _script_steps(fake_structured) -> None:
    for n in range(1, 11):
        fake_structured.set(f"step_{n}", _step_output(n))


def _script_qc_ship(fake_structured) -> None:
    fake_structured.set(
        "ff_qc1",
        {
            "critic": "traceability_auditor",
            "findings": [],
            "cleanSections": [],
            "summaryJudgement": "Clean.",
        },
    )
    fake_structured.set(
        "ff_qc2",
        {
            "critic": "coherence_checker",
            "findings": [],
            "passedChecks": [],
            "summaryJudgement": "Coherent.",
        },
    )
    fake_structured.set(
        "ff_qc3",
        {
            "critic": "reader_persona_panel",
            "readers": [],
            "convergentIssues": [],
            "summaryJudgement": "Fine.",
        },
    )
    fake_structured.set(
        "ff_qc4",
        {
            "critic": "red_team",
            "findings": [],
            "survivedAttacks": [],
            "strongestCounterargument": "",
            "summaryJudgement": "Holds.",
        },
    )
    fake_structured.set(
        "ff_qc5",
        {
            "critic": "surprise_genericity_scorer",
            "sectionVerdicts": [],
            "mostGenericParagraphs": [],
            "mostInsightDense": [],
            "truismCheck": [],
            "nonObviousClaims": [],
            "surpriseVerdict": {"score": "adequate", "cause": "substrate", "reasoning": "ok"},
            "protectionList": [],
            "summaryJudgement": "Specific enough.",
        },
    )


async def _run_to_completion(graph, config, state) -> dict:
    """``ainvoke`` returns normally with an ``__interrupt__`` key rather than
    raising — unlike ``astream``, which graph/runner.py iterates and catches
    ``GraphInterrupt`` around (see graph/runner.py's own docstring)."""
    payload: Any = state
    while True:
        final = await graph.ainvoke(payload, config)
        pending = final.get("__interrupt__")
        if not pending:
            return final
        value = pending[0].value
        assert "stepNumber" in value
        assert "output" in value
        # LangGraph treats an empty dict as "nothing to resume with" and
        # re-issues the same interrupt — the resume value must be truthy.
        payload = Command(resume={"approved": True})


async def test_form_filling_10step_runs_all_gates_and_ships(
    graph, fake_structured, fake_checkpoints, fake_search
):
    _script_steps(fake_structured)
    _script_qc_ship(fake_structured)

    state = initial_state(
        run_id="form_filling_10step:ff-1",
        session_id="ff-1",
        workflow="form_filling_10step",
        project_id=42,
        request=_request(),
    )
    config = {"configurable": {"thread_id": "form_filling_10step:ff-1"}}
    final = await _run_to_completion(graph, config, state)

    # 9 checkpoint calls fired (steps 1-9 mid-run), none for step 10 (that's the
    # run's normal final delivery instead).
    assert len(fake_checkpoints) == 9
    assert [c["body"]["stepNumber"] for c in fake_checkpoints] == list(range(1, 10))
    # runId echoes the raw backend sessionId, not our internal composite run_id
    # (the backend's n8n_strategy_submission_logs row is keyed by the former).
    assert all(c["body"]["runId"] == "ff-1" for c in fake_checkpoints)

    # step 4's scenario blocks got method-tagged (n8n "Code in JavaScript6" port).
    assert final["artifacts"]["step_4"]["0"]["type"] == "GBN"

    # dependency-graph context injection: step 5 depends on 2,3,4 — nothing enforced
    # structurally here beyond "it ran without raising", but confirm all step
    # artifacts landed.
    assert all(f"step_{n}" in final["artifacts"] for n in range(1, 11))

    # SHIP path: no findings -> no revision.
    assert final["artifacts"]["qcRevised"] is False

    result = final["result"]
    assert result["runId"] == "ff-1"
    assert result["stepNumber"] == 10
    assert result["stepKey"] == "step10"
    assert result["output"]["executiveSummary"] or result["output"].get("executive_summary")
