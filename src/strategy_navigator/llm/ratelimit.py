"""Per-model in-process concurrency guard.

With a single LiteLLM instance in front, LiteLLM's own router is the authoritative
cross-worker rate limiter (rpm/tpm/cooldown). This semaphore is a cheap local
backstop so one worker process cannot open 50 sockets at once and starve itself.

Ceilings come from ``SN_LLM_CONCURRENCY``. Unknown models get a default of 4.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict

from strategy_navigator.config import settings

_DEFAULT = 4
_semaphores: dict[str, asyncio.Semaphore] = {}
_lock = asyncio.Lock()
_waiters: dict[str, int] = defaultdict(int)


async def _get(model: str) -> asyncio.Semaphore:
    sem = _semaphores.get(model)
    if sem is None:
        async with _lock:
            sem = _semaphores.get(model)
            if sem is None:
                limit = settings.llm_concurrency.get(model, _DEFAULT)
                sem = asyncio.Semaphore(limit)
                _semaphores[model] = sem
    return sem


class _Slot:
    def __init__(self, model: str) -> None:
        self.model = model
        self._sem: asyncio.Semaphore | None = None

    async def __aenter__(self) -> None:
        self._sem = await _get(self.model)
        _waiters[self.model] += 1
        await self._sem.acquire()
        _waiters[self.model] -= 1

    async def __aexit__(self, *exc: object) -> None:
        assert self._sem is not None
        self._sem.release()


def slot(model: str) -> _Slot:
    """``async with slot(model):`` around a model call."""
    return _Slot(model)


def pending(model: str) -> int:
    return _waiters.get(model, 0)
