"""The shared graph state.

Every workflow graph uses this one schema. Stages read ``request`` (the validated
inbound payload as a dict) and write their output under ``artifacts[<stage>]``.
``result`` is the finished callback body. Reducers let parallel branches
(e.g. voting fan-out) merge without clobbering each other.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


def _merge_dict(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    return {**left, **right}


class PipelineState(TypedDict, total=False):
    # --- identity (set once at invoke) ---
    run_id: str
    session_id: str
    workflow: str
    project_id: int | None

    # --- inbound ---
    request: dict[str, Any]

    # --- working store; stages merge their outputs in ---
    artifacts: Annotated[dict[str, Any], _merge_dict]

    # --- fan-out accumulator (voting children, section generation, ...) ---
    partials: Annotated[list[Any], operator.add]

    # --- terminal ---
    result: dict[str, Any] | None
    errors: Annotated[list[str], operator.add]

    # --- fan-out scratch: payload handed to a single Send'd child node ---
    _child: dict[str, Any]


def initial_state(
    *, run_id: str, session_id: str, workflow: str, project_id: int | None, request: dict[str, Any]
) -> PipelineState:
    return PipelineState(
        run_id=run_id,
        session_id=session_id,
        workflow=workflow,
        project_id=project_id,
        request=request,
        artifacts={},
        partials=[],
        result=None,
        errors=[],
    )
