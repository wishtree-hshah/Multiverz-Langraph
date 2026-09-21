"""The one queue task: run (or resume) a workflow graph.

Failure handling, three tiers:
1. transient inside a run  -> LangGraph node retry / LLM client retry (never
   leaves the lane)
2. run raises a TransientError / unexpected error -> caught here, run re-deferred
   onto ``sn_retry`` with high priority and an incremented attempt count. The
   LangGraph checkpoint means the retry RESUMES, it does not restart.
3. attempts exhausted (``SN_RUN_MAX_ATTEMPTS``) or PermanentError -> dead-letter
   table + structured error log (hook your alerting on ``run.dead``).
"""

from __future__ import annotations

import traceback
from typing import Any

from strategy_navigator.config import settings
from strategy_navigator.constants import (
    PRIORITY_FRESH,
    PRIORITY_HUMAN_RESUME,
    PRIORITY_RETRY,
    Workflow,
)
from strategy_navigator.db.engine import session_scope
from strategy_navigator.db.models import RunStatus
from strategy_navigator.db.repositories import DeadLetterRepository, RunRepository
from strategy_navigator.errors import PermanentError
from strategy_navigator.graph.runner import OutcomeStatus, run_workflow_graph
from strategy_navigator.logging import bind_context, get_logger
from strategy_navigator.queue.app import app
from strategy_navigator.queue.lanes import QUEUE_RETRY, lane_for, queue_for_workflow

log = get_logger(__name__)


@app.task(name="run_workflow", queue="sn_short", pass_context=True)
async def run_workflow(
    context: Any,
    *,
    run_id: str,
    session_id: str,
    workflow: str,
    project_id: int | None = None,
    request: dict[str, Any] | None = None,
    resume_value: Any = None,
    attempt: int = 1,
) -> dict[str, Any]:
    wf = Workflow(workflow)
    request = request or {}

    with bind_context(run_id=run_id, session_id=session_id, workflow=workflow, attempt=attempt):
        async with session_scope() as s:
            await RunRepository(s).mark(run_id, RunStatus.RUNNING, attempts=attempt)

        try:
            outcome = await run_workflow_graph(
                workflow=wf,
                run_id=run_id,
                session_id=session_id,
                project_id=project_id,
                request=request,
                resume_value=resume_value,
            )
        except PermanentError as exc:
            await _dead_letter(run_id, session_id, workflow, attempt, exc, request)
            return {"status": "dead", "reason": "permanent"}
        except Exception as exc:  # transient / unknown -> retry lane
            if attempt >= settings.run_max_attempts:
                await _dead_letter(run_id, session_id, workflow, attempt, exc, request)
                return {"status": "dead", "reason": "attempts_exhausted"}
            await _requeue_retry(
                run_id=run_id,
                session_id=session_id,
                workflow=workflow,
                project_id=project_id,
                request=request,
                resume_value=resume_value,
                attempt=attempt + 1,
                error=exc,
            )
            return {"status": "retry_scheduled", "attempt": attempt + 1}

        # --- terminal / paused ---
        if outcome.status == OutcomeStatus.WAITING_HUMAN:
            async with session_scope() as s:
                await RunRepository(s).mark(
                    run_id,
                    RunStatus.WAITING_HUMAN,
                    interrupt_payload={"value": outcome.interrupt},
                )
            log.info("run.waiting_human")
            return {"status": "waiting_human"}

        result = outcome.result or {}
        if outcome.token_usage:
            result.setdefault("tokenUsage", outcome.token_usage)

        async with session_scope() as s:
            await RunRepository(s).mark(run_id, RunStatus.SUCCEEDED, result=result)

        await _deliver_callback(run_id, session_id, workflow, result)
        log.info("run.succeeded")
        return {"status": "succeeded"}


async def _requeue_retry(
    *,
    run_id: str,
    session_id: str,
    workflow: str,
    project_id: int | None,
    request: dict[str, Any],
    resume_value: Any,
    attempt: int,
    error: Exception,
) -> None:
    log.warning("run.retry_scheduled", attempt=attempt, error=str(error))
    async with session_scope() as s:
        await RunRepository(s).mark(
            run_id, RunStatus.FAILED, attempts=attempt - 1, error_message=str(error)
        )
    await run_workflow.configure(queue=QUEUE_RETRY, priority=PRIORITY_RETRY).defer_async(
        run_id=run_id,
        session_id=session_id,
        workflow=workflow,
        project_id=project_id,
        request=request,
        resume_value=resume_value,
        attempt=attempt,
    )


async def _dead_letter(
    run_id: str,
    session_id: str,
    workflow: str,
    attempt: int,
    exc: Exception,
    payload: dict[str, Any],
) -> None:
    log.error(
        "run.dead",
        attempt=attempt,
        error_type=type(exc).__name__,
        error=str(exc),
        exc_info=True,
    )
    async with session_scope() as s:
        await RunRepository(s).mark(
            run_id, RunStatus.DEAD, attempts=attempt, error_message=str(exc)
        )
        await DeadLetterRepository(s).add(
            run_id=run_id,
            session_id=session_id,
            workflow=workflow,
            attempts=attempt,
            error_type=type(exc).__name__,
            error_message=str(exc),
            traceback=traceback.format_exc(),
            payload=payload,
        )
    await _deliver_callback(
        run_id, session_id, workflow, {"sessionId": session_id, "errorMessage": str(exc)}
    )


async def _deliver_callback(
    run_id: str, session_id: str, workflow: str, body: dict[str, Any]
) -> None:
    from strategy_navigator.callbacks.client import post_callback

    async with session_scope() as s:
        run = await RunRepository(s).get(run_id)
    callback_url = run.callback_url if run else None
    await post_callback(
        workflow=workflow, callback_url=callback_url, session_id=session_id, body=body
    )


async def enqueue_run(
    *,
    run_id: str,
    session_id: str,
    workflow: Workflow,
    project_id: int | None,
    request: dict[str, Any],
    callback_url: str | None,
    voting_session_id: int | None = None,
    resume_value: Any = None,
) -> None:
    """Insert the run row and defer the job onto its lane's queue."""
    lane = lane_for(workflow)
    async with session_scope() as s:
        await RunRepository(s).upsert_queued(
            run_id=run_id,
            session_id=session_id,
            workflow=str(workflow),
            lane=str(lane),
            payload=request,
            callback_url=callback_url,
            project_id=project_id,
            voting_session_id=voting_session_id,
        )
    queue = queue_for_workflow(workflow)
    priority = PRIORITY_HUMAN_RESUME if resume_value is not None else PRIORITY_FRESH
    await run_workflow.configure(queue=queue, priority=priority).defer_async(
        run_id=run_id,
        session_id=session_id,
        workflow=str(workflow),
        project_id=project_id,
        request=request,
        resume_value=resume_value,
        attempt=1,
    )
    log.info("run.enqueued", queue=queue, lane=str(lane), priority=priority)
