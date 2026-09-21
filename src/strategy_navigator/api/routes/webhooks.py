"""n8n-compatible trigger endpoints.

challenges-backend already POSTs ``{ workflow_name, payload }`` to a per-workflow
webhook URL (see n8n-http-client.adapter.ts). Point every
``N8N_WEBHOOK_*_URL`` env var at ``POST /webhooks/trigger`` here and nothing on
the backend changes.

The endpoint validates + adapts the payload, creates the run row, enqueues onto
the correct lane, and returns ``202 Accepted`` immediately. The result is
delivered later via the callback client — same async contract as n8n.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body
from pydantic import BaseModel

from strategy_navigator.api.payload_adapter import adapt
from strategy_navigator.constants import N8N_WORKFLOW_NAME, Workflow
from strategy_navigator.errors import InvalidPayloadError, UnknownWorkflowError
from strategy_navigator.logging import bind_context, get_logger
from strategy_navigator.queue.tasks import enqueue_run
from strategy_navigator.stages import is_ported

log = get_logger(__name__)
router = APIRouter()


class TriggerEnvelope(BaseModel):
    workflow_name: str
    payload: Any


class TriggerAccepted(BaseModel):
    accepted: bool = True
    run_id: str
    workflow: str
    lane: str
    ported: bool


def _run_id(workflow: Workflow, session_id: str) -> str:
    return f"{workflow}:{session_id}"


async def _dispatch(workflow: Workflow, raw: Any) -> TriggerAccepted:
    request = adapt(workflow, raw)
    session_id = request["sessionId"]
    # capstone_substrate has no top-level "project" block (see payload_adapter.adapt).
    project_id = int(request.get("projectId") or request["project"]["projectId"])
    run_id = _run_id(workflow, session_id)

    with bind_context(run_id=run_id, session_id=session_id, workflow=str(workflow)):
        from strategy_navigator.constants import WORKFLOW_LANE, Lane

        await enqueue_run(
            run_id=run_id,
            session_id=session_id,
            workflow=workflow,
            project_id=project_id,
            request=request,
            callback_url=request.get("callbackUrl"),
            voting_session_id=request.get("votingSessionId"),
        )
        lane = WORKFLOW_LANE.get(workflow, Lane.SHORT)
        log.info("webhook.accepted", lane=str(lane))
        return TriggerAccepted(
            run_id=run_id, workflow=str(workflow), lane=str(lane), ported=is_ported(workflow)
        )


@router.post("/trigger", response_model=TriggerAccepted, status_code=202)
async def trigger(envelope: TriggerEnvelope = Body(...)) -> TriggerAccepted:
    name = envelope.workflow_name
    workflow = N8N_WORKFLOW_NAME.get(name)
    if workflow is None:
        raise UnknownWorkflowError(f"Unknown workflow_name {name!r}")
    if envelope.payload is None:
        raise InvalidPayloadError("missing payload")
    return await _dispatch(workflow, envelope.payload)


@router.post("/{workflow}", response_model=TriggerAccepted, status_code=202)
async def trigger_by_path(workflow: str, payload: Any = Body(...)) -> TriggerAccepted:
    """Alternative: one URL per workflow using the internal name, bare payload."""
    try:
        wf = Workflow(workflow)
    except ValueError as exc:
        raise UnknownWorkflowError(f"Unknown workflow {workflow!r}") from exc
    return await _dispatch(wf, payload)
