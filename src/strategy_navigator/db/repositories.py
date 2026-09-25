"""Thin data-access helpers. No business logic — callers own transactions via
:func:`strategy_navigator.db.engine.session_scope`.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_navigator.db.models import (
    DeadLetter,
    RunRecord,
    RunStatus,
    SearchCache,
    TokenUsage,
)


class RunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def get(self, run_id: str) -> RunRecord | None:
        return await self.s.get(RunRecord, run_id)

    async def upsert_queued(
        self,
        *,
        run_id: str,
        session_id: str,
        workflow: str,
        lane: str,
        payload: dict,
        callback_url: str | None,
        project_id: int | None,
        voting_session_id: int | None,
    ) -> None:
        stmt = insert(RunRecord).values(
            run_id=run_id,
            session_id=session_id,
            workflow=workflow,
            lane=lane,
            project_id=project_id,
            voting_session_id=voting_session_id,
            callback_url=callback_url,
            request_payload=payload,
            status=RunStatus.QUEUED,
        )
        # Re-triggering the same session id is idempotent: keep the original row.
        stmt = stmt.on_conflict_do_nothing(index_elements=[RunRecord.run_id])
        await self.s.execute(stmt)

    async def mark(
        self,
        run_id: str,
        status: RunStatus,
        *,
        attempts: int | None = None,
        result: dict | None = None,
        error_message: str | None = None,
        interrupt_payload: dict | None = None,
    ) -> None:
        values: dict[str, object] = {"status": status, "updated_at": dt.datetime.now(dt.UTC)}
        if attempts is not None:
            values["attempts"] = attempts
        if result is not None:
            values["result"] = result
        if error_message is not None:
            values["error_message"] = error_message
        if interrupt_payload is not None:
            values["interrupt_payload"] = interrupt_payload
        if status == RunStatus.RUNNING:
            values["started_at"] = dt.datetime.now(dt.UTC)
        if status in (RunStatus.SUCCEEDED, RunStatus.DEAD):
            values["finished_at"] = dt.datetime.now(dt.UTC)
        await self.s.execute(update(RunRecord).where(RunRecord.run_id == run_id).values(**values))


class SearchCacheRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def get(self, query_hash: str) -> dict | None:
        row = await self.s.get(SearchCache, query_hash)
        if row is None or row.expires_at < dt.datetime.now(dt.UTC):
            return None
        return row.response

    async def put(
        self, *, query_hash: str, op: str, query: str, response: dict, ttl_s: int
    ) -> None:
        now = dt.datetime.now(dt.UTC)
        stmt = insert(SearchCache).values(
            query_hash=query_hash,
            op=op,
            query=query,
            response=response,
            expires_at=now + dt.timedelta(seconds=ttl_s),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[SearchCache.query_hash],
            set_={"response": response, "expires_at": now + dt.timedelta(seconds=ttl_s)},
        )
        await self.s.execute(stmt)

    async def purge_expired(self) -> int:
        res = await self.s.execute(
            delete(SearchCache).where(SearchCache.expires_at < dt.datetime.now(dt.UTC))
        )
        return res.rowcount or 0


class DeadLetterRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def add(
        self,
        *,
        run_id: str,
        session_id: str,
        workflow: str,
        attempts: int,
        error_type: str,
        error_message: str,
        traceback: str | None,
        payload: dict,
    ) -> None:
        self.s.add(
            DeadLetter(
                run_id=run_id,
                session_id=session_id,
                workflow=workflow,
                attempts=attempts,
                error_type=error_type,
                error_message=error_message,
                traceback=traceback,
                payload=payload,
            )
        )

    async def list_unreplayed(self, limit: int = 100) -> list[DeadLetter]:
        res = await self.s.execute(
            select(DeadLetter)
            .where(DeadLetter.replayed_at.is_(None))
            .order_by(DeadLetter.created_at.desc())
            .limit(limit)
        )
        return list(res.scalars())


class TokenUsageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def record(
        self,
        *,
        run_id: str,
        session_id: str,
        workflow: str,
        stage: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float,
    ) -> None:
        self.s.add(
            TokenUsage(
                run_id=run_id,
                session_id=session_id,
                workflow=workflow,
                stage=stage,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                cost_usd=cost_usd,
            )
        )
