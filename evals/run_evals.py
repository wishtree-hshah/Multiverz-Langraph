"""Stage output-quality evals. See evals/README.md.

Run: uv run strategy-navigator eval   (needs a live LLM gateway)
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver

from strategy_navigator.graph.state import initial_state
from strategy_navigator.logging import configure_logging, get_logger
from strategy_navigator.stages import domain_agent, idea_extraction

log = get_logger("evals")
DATASET = Path(__file__).parent / "datasets" / "sample_projects.jsonl"
_PLACEHOLDER = ("placeholder", "lorem ipsum", "TODO", "[PLACEHOLDER]")


def _cases() -> list[dict]:
    return [json.loads(line) for line in DATASET.read_text().splitlines() if line.strip()]


def _check(name: str, cond: bool, detail: str = "") -> bool:
    mark = "PASS" if cond else "FAIL"
    log.info("eval.check", check=name, result=mark, detail=detail)
    return cond


async def eval_domain_agent(project: dict) -> list[bool]:
    graph = domain_agent.build().compile(checkpointer=MemorySaver())
    state = initial_state(
        run_id=f"domain_agent:{project['sessionId']}",
        session_id=project["sessionId"],
        workflow="domain_agent",
        project_id=project["projectId"],
        request={"sessionId": project["sessionId"], "project": project, "minAgents": 3, "maxAgents": 6},
    )
    out = await graph.ainvoke(state, {"configurable": {"thread_id": state["run_id"]}})
    agents = out["result"]["agents"]
    return [
        _check("domain_agent.count", 3 <= len(agents) <= 6, f"{len(agents)} personas"),
        _check("domain_agent.fields", all(a["name"] and a["designation"] and a["description"] for a in agents)),
        _check(
            "domain_agent.distinct_designations",
            len({a["designation"].lower() for a in agents}) == len(agents),
        ),
        _check(
            "domain_agent.no_placeholder",
            not any(p in json.dumps(agents).lower() for p in map(str.lower, _PLACEHOLDER)),
        ),
    ]


async def eval_idea_extraction(project: dict) -> list[bool]:
    graph = idea_extraction.build().compile(checkpointer=MemorySaver())
    agent = {"id": 1, "name": "Sofia Marchetti", "designation": "Grid Economist", "description": "Focus on capital efficiency and tariff design.", "isDomainSpecific": True}
    state = initial_state(
        run_id=f"idea_extraction:{project['sessionId']}",
        session_id=project["sessionId"],
        workflow="idea_extraction",
        project_id=project["projectId"],
        request={
            "sessionId": project["sessionId"],
            "project": project,
            "agent": agent,
            "categories": ["Commercial", "Operational", "Regulatory"],
            "ideaCount": 4,
        },
    )
    out = await graph.ainvoke(state, {"configurable": {"thread_id": state["run_id"]}})
    ideas = out["result"]["ideas"]
    return [
        _check("idea_extraction.count", len(ideas) == 4, f"{len(ideas)} ideas"),
        _check("idea_extraction.summaries", all(len(i["summary"]) > 60 for i in ideas)),
        _check("idea_extraction.provenance", all(i["agentId"] == 1 for i in ideas)),
        _check("idea_extraction.distinct_titles", len({i["title"] for i in ideas}) == len(ideas)),
    ]


async def main() -> int:
    configure_logging()
    results: list[bool] = []
    for project in _cases():
        log.info("eval.case", project=project["projectName"])
        results += await eval_domain_agent(project)
        results += await eval_idea_extraction(project)
    passed, total = sum(results), len(results)
    log.info("eval.summary", passed=passed, total=total)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
