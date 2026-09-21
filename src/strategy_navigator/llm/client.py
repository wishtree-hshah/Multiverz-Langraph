"""Async chat client.

Thin wrapper over the ``litellm`` SDK pointed at the gateway (``SN_LLM_BASE_URL``).
Responsibilities kept here (everything the n8n ``lmChatOpenRouter`` node + LiteLLM
config did):

* retry transient failures with backoff (on top of LiteLLM's own retries)
* app-level fallback ``default_model -> fast_model`` if the gateway 5xxes the chain
* per-model concurrency slot (see :mod:`strategy_navigator.llm.ratelimit`)
* funnel ``usage`` into :mod:`strategy_navigator.llm.tokens`
* a tracing span per call

If you delete the LiteLLM container, set ``SN_LLM_BASE_URL`` to
``https://openrouter.ai/api/v1`` and prefix model names with ``openrouter/`` —
nothing else changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import litellm
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from strategy_navigator.config import settings
from strategy_navigator.errors import LLMError, LLMTimeoutError
from strategy_navigator.llm import tokens
from strategy_navigator.llm.ratelimit import slot
from strategy_navigator.logging import get_logger
from strategy_navigator.observability import span

log = get_logger(__name__)

# The SDK talks to our gateway; don't let it also retry against real providers.
litellm.drop_params = True
litellm.suppress_debug_info = True

Message = dict[str, str]

_RETRYABLE = (
    litellm.exceptions.RateLimitError,
    litellm.exceptions.APIConnectionError,
    litellm.exceptions.Timeout,
    litellm.exceptions.InternalServerError,
    litellm.exceptions.ServiceUnavailableError,
)


@dataclass(slots=True)
class ChatResult:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    finish_reason: str | None
    raw: dict[str, Any]


class LLMClient:
    def __init__(self) -> None:
        self._base_url = settings.llm_base_url
        self._api_key = settings.llm_api_key
        self._default = settings.llm_default_model
        self._fast = settings.llm_fast_model

    def resolve_model(self, model: str | None, *, fast: bool = False) -> str:
        if model:
            return model
        return self._fast if fast else self._default

    async def chat(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        fast: bool = False,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
        stage: str = "-",
        extra: dict[str, Any] | None = None,
    ) -> ChatResult:
        primary = self.resolve_model(model, fast=fast)
        try:
            return await self._chat_once(
                messages,
                model=primary,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
                stage=stage,
                extra=extra,
            )
        except _RETRYABLE as exc:
            fallback = self._fast if primary != self._fast else self._default
            log.warning(
                "llm.fallback", stage=stage, primary=primary, fallback=fallback, error=str(exc)
            )
            return await self._chat_once(
                messages,
                model=fallback,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
                stage=stage,
                extra=extra,
            )

    @retry(
        retry=retry_if_exception_type(_RETRYABLE),
        wait=wait_exponential(multiplier=2, min=2, max=60),
        stop=stop_after_attempt(settings.llm_max_retries),
        reraise=True,
    )
    async def _chat_once(
        self,
        messages: list[Message],
        *,
        model: str,
        temperature: float,
        max_tokens: int | None,
        response_format: dict[str, Any] | None,
        stage: str,
        extra: dict[str, Any] | None,
    ) -> ChatResult:
        params: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "api_base": self._base_url,
            "api_key": self._api_key,
            "temperature": temperature,
            "timeout": settings.llm_request_timeout_s,
            "num_retries": 0,  # tenacity owns retries here
        }
        if max_tokens:
            params["max_tokens"] = max_tokens
        if response_format:
            params["response_format"] = response_format
        if extra:
            params.update(extra)

        with span("llm.chat", **{"llm.model": model, "llm.stage": stage}):
            async with slot(model):
                try:
                    resp = await litellm.acompletion(**params)
                except litellm.exceptions.Timeout as exc:
                    raise LLMTimeoutError(f"{model} timed out: {exc}") from exc
                except litellm.exceptions.APIError as exc:
                    raise LLMError(f"{model} API error: {exc}") from exc

        choice = resp.choices[0]
        usage = resp.get("usage") or {}
        prompt_toks = int(usage.get("prompt_tokens", 0))
        completion_toks = int(usage.get("completion_tokens", 0))
        try:
            cost = float(litellm.completion_cost(completion_response=resp) or 0.0)
        except Exception:
            cost = 0.0

        await tokens.record(
            stage=stage,
            model=model,
            prompt_tokens=prompt_toks,
            completion_tokens=completion_toks,
            cost_usd=cost,
        )

        return ChatResult(
            text=choice.message.content or "",
            model=model,
            prompt_tokens=prompt_toks,
            completion_tokens=completion_toks,
            cost_usd=cost,
            finish_reason=getattr(choice, "finish_reason", None),
            raw=resp.model_dump() if hasattr(resp, "model_dump") else dict(resp),
        )


@lru_cache
def get_llm() -> LLMClient:
    return LLMClient()
