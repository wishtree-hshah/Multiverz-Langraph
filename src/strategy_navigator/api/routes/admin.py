"""Operational endpoints: dead-letter inspection/replay, token spend."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from strategy_navigator.constants import Workflow
from strategy_navigator.db.engine import session_scope
from strategy_navigator.db.models import DeadLetter, TokenUsage
from strategy_navigator.db.repositories import DeadLetterRepository, RunRepository
from strategy_navigator.queue.tasks import enqueue_run

router = APIRouter()


@router.get("/dead-letter")
async def list_dead_letter(limit: int = 100) -> list[dict]:
    async with session_scope() as s:
        rows = await DeadLetterRepository(s).list_unreplayed(limit)
    return [
        {
            "id": r.id,
            "run_id": r.run_id,
            "session_id": r.session_id,
            "workflow": r.workflow,
            "attempts": r.attempts,
            "error_type": r.error_type,
            "error_message": r.error_message,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.post("/dead-letter/{dead_id}/replay", status_code=202)
async def replay_dead_letter(dead_id: int) -> dict:
    async with session_scope() as s:
        dl = await s.get(DeadLetter, dead_id)
        if dl is None:
            raise HTTPException(404, "dead-letter row not found")
        run = await RunRepository(s).get(dl.run_id)

    await enqueue_run(
        run_id=dl.run_id,
        session_id=dl.session_id,
        workflow=Workflow(dl.workflow),
        project_id=run.project_id if run else None,
        request=dl.payload,
        callback_url=run.callback_url if run else None,
    )
    async with session_scope() as s:
        dl = await s.get(DeadLetter, dead_id)
        if dl is not None:
            from datetime import UTC, datetime

            dl.replayed_at = datetime.now(UTC)
    return {"replayed": dl.run_id}


@router.get("/token-usage")
async def token_usage(session_id: str | None = None) -> list[dict]:
    async with session_scope() as s:
        stmt = select(
            TokenUsage.workflow,
            TokenUsage.model,
            func.sum(TokenUsage.prompt_tokens),
            func.sum(TokenUsage.completion_tokens),
            func.sum(TokenUsage.cost_usd),
        ).group_by(TokenUsage.workflow, TokenUsage.model)
        if session_id:
            stmt = stmt.where(TokenUsage.session_id == session_id)
        rows = (await s.execute(stmt)).all()
    return [
        {
            "workflow": w,
            "model": m,
            "promptTokens": int(pt or 0),
            "completionTokens": int(ct or 0),
            "costUsd": round(float(cost or 0), 6),
        }
        for w, m, pt, ct, cost in rows
    ]
