"""Token / cost accounting.

Every model call funnels its ``usage`` here. Two sinks:
* an in-memory per-run accumulator (read by the graph runner to attach a
  ``tokenUsage`` block to the backend callback, matching the old n8n shape)
* the ``sn_token_usage`` table (durable, queryable — replaces n8n Token Counter)
"""

from __future__ import annotations

from collections import defaultdict
from contextvars import ContextVar
from dataclasses import dataclass, field

from strategy_navigator.db.engine import session_scope
from strategy_navigator.db.repositories import TokenUsageRepository
from strategy_navigator.logging import get_logger

log = get_logger(__name__)


@dataclass
class ModelTally:
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class RunTally:
    run_id: str = ""
    session_id: str = ""
    workflow: str = ""
    by_model: dict[str, ModelTally] = field(default_factory=dict)

    def add(self, model: str, prompt: int, completion: int, cost: float) -> None:
        t = self.by_model.setdefault(model, ModelTally(model))
        t.prompt_tokens += prompt
        t.completion_tokens += completion
        t.cost_usd += cost

    def as_callback_list(self) -> list[dict]:
        """Matches challenges-backend's per-model tokenUsage array shape."""
        return [
            {
                "modelName": t.model,
                "promptTokens": t.prompt_tokens,
                "completionTokens": t.completion_tokens,
                "totalTokens": t.total_tokens,
                "costUsd": round(t.cost_usd, 6),
            }
            for t in self.by_model.values()
        ]


_current: ContextVar[RunTally | None] = ContextVar("token_tally", default=None)


def start_run_tally(run_id: str, session_id: str, workflow: str) -> RunTally:
    tally = RunTally(run_id=run_id, session_id=session_id, workflow=workflow)
    _current.set(tally)
    return tally


def current_tally() -> RunTally | None:
    return _current.get()


async def record(
    *, stage: str, model: str, prompt_tokens: int, completion_tokens: int, cost_usd: float
) -> None:
    tally = _current.get()
    if tally is not None:
        tally.add(model, prompt_tokens, completion_tokens, cost_usd)
    log.debug(
        "llm.usage",
        stage=stage,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=round(cost_usd, 6),
    )
    if tally is None:
        return
    try:
        async with session_scope() as s:
            await TokenUsageRepository(s).record(
                run_id=tally.run_id,
                session_id=tally.session_id,
                workflow=tally.workflow,
                stage=stage,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_usd=cost_usd,
            )
    except Exception as exc:  # accounting must never break a run
        log.warning("llm.usage_persist_failed", error=str(exc))


def aggregate_by_model(tallies: list[RunTally]) -> list[dict]:
    merged: dict[str, ModelTally] = defaultdict(lambda: ModelTally(""))
    for rt in tallies:
        for m, t in rt.by_model.items():
            mm = merged[m]
            mm.model = m
            mm.prompt_tokens += t.prompt_tokens
            mm.completion_tokens += t.completion_tokens
            mm.cost_usd += t.cost_usd
    return [
        {
            "modelName": t.model,
            "promptTokens": t.prompt_tokens,
            "completionTokens": t.completion_tokens,
            "totalTokens": t.total_tokens,
            "costUsd": round(t.cost_usd, 6),
        }
        for t in merged.values()
    ]
