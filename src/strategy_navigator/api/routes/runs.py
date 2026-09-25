"""Run status + human-gate resume.

When a workflow graph calls ``interrupt(...)`` (e.g. "user selects ideas", "user
picks archetype"), the run is parked as ``waiting_human`` and its interrupt
payload stored. The frontend/backend fetches it via ``GET /runs/{run_id}``, and
resumes with the user's choice via ``POST /runs/{run_id}/resume`` — which
re-enqueues the run (priority above fresh work) to continue from the checkpoint.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from strategy_navigator.constants import Workflow
from strategy_navigator.db.engine import session_scope
from strategy_navigator.db.models import RunStatus
from strategy_navigator.db.repositories import RunRepository
from strategy_navigator.queue.tasks import enqueue_run

router = APIRouter()


class RunView(BaseModel):
    run_id: str
    session_id: str
    workflow: str
    lane: str
    status: str
    attempts: int
    error_message: str | None
    interrupt: Any | None
    result: Any | None


class ResumeRequest(BaseModel):
    value: Any


@router.get("/{run_id}", response_model=RunView)
async def get_run(run_id: str) -> RunView:
    async with session_scope() as s:
        run = await RunRepository(s).get(run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    return RunView(
        run_id=run.run_id,
        session_id=run.session_id,
        workflow=run.workflow,
        lane=run.lane,
        status=run.status,
        attempts=run.attempts,
        error_message=run.error_message,
        interrupt=(run.interrupt_payload or {}).get("value") if run.interrupt_payload else None,
        result=run.result,
    )


@router.post("/{run_id}/resume", response_model=RunView, status_code=202)
async def resume_run(run_id: str, body: ResumeRequest) -> RunView:
    async with session_scope() as s:
        run = await RunRepository(s).get(run_id)
        if run is None:
            raise HTTPException(404, "run not found")
        if run.status != RunStatus.WAITING_HUMAN:
            raise HTTPException(409, f"run is {run.status}, not waiting_human")

    await enqueue_run(
        run_id=run.run_id,
        session_id=run.session_id,
        workflow=Workflow(run.workflow),
        project_id=run.project_id,
        request=run.request_payload,
        callback_url=run.callback_url,
        voting_session_id=run.voting_session_id,
        resume_value=body.value,
    )
    return await get_run(run_id)
