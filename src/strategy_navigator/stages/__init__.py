"""Stage registry: ``Workflow -> graph builder``.

A "graph builder" is a zero-arg callable returning an *uncompiled* ``StateGraph``
(the runner compiles it with the checkpointer). Ported workflows point at their
module's ``build``; the rest use :class:`StubStage`, which fails loudly.

To port a workflow:
1. implement ``strategy_navigator/stages/<workflow>.py`` with a ``build()``
2. fill ``strategy_navigator/prompts/<workflow>.md``
3. swap its entry here from ``StubStage(...)`` to the real ``build``
4. add tests under ``tests/stages/``
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from strategy_navigator.constants import Workflow
from strategy_navigator.errors import UnknownWorkflowError
from strategy_navigator.stages import (
    capstone_substrate,
    custom_archetype,
    domain_agent,
    foresight_consolidation,
    form_filling_10step,
    idea_extraction,
    rapid_consolidation,
    report_render,
    voting,
)
from strategy_navigator.stages.base import StubStage

GraphBuilder = Callable[[], Any]

_REGISTRY: dict[Workflow, GraphBuilder] = {
    # --- ported ---
    Workflow.DOMAIN_AGENT: domain_agent.build,
    Workflow.IDEA_EXTRACTION: idea_extraction.build,
    Workflow.VOTING: voting.build,
    Workflow.CUSTOM_ARCHETYPE: custom_archetype.build,
    Workflow.FORESIGHT_CONSOLIDATION: foresight_consolidation.build,
    Workflow.RAPID_CONSOLIDATION: rapid_consolidation.build,
    Workflow.REPORT_RENDER: report_render.build,
    Workflow.CAPSTONE_SUBSTRATE: capstone_substrate.build,
    Workflow.FORM_FILLING_10STEP: form_filling_10step.build,
    # --- stubs (port next) ---
    Workflow.STRATEGY_FORM_IDEA_GENERATION: StubStage(Workflow.STRATEGY_FORM_IDEA_GENERATION),
    Workflow.STRATEGIC_FORESIGHT_REPORT: StubStage(Workflow.STRATEGIC_FORESIGHT_REPORT),
}


def get_graph_builder(workflow: Workflow) -> GraphBuilder:
    try:
        return _REGISTRY[workflow]
    except KeyError as exc:
        raise UnknownWorkflowError(f"No graph registered for {workflow!r}") from exc


def is_ported(workflow: Workflow) -> bool:
    return not isinstance(_REGISTRY.get(workflow), StubStage)


def ported_workflows() -> list[Workflow]:
    return [w for w in _REGISTRY if is_ported(w)]
