"""Shared fixtures.

Unit tests never touch Postgres, LiteLLM, or the network. LLM calls are faked at
two seams:
* ``strategy_navigator.llm.client.LLMClient.chat``
* ``strategy_navigator.llm.structured.generate_structured``
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import pytest

os.environ.setdefault("SN_DATABASE_URL", "postgresql://sn:sn@localhost:5432/sn_test")
os.environ.setdefault("SN_LLM_API_KEY", "sk-test")
os.environ.setdefault("SN_JINA_API_KEY", "jina-test")


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Iterator[None]:
    from strategy_navigator.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def fake_chat(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Patch LLMClient.chat to return a scripted response."""
    from strategy_navigator.llm.client import ChatResult

    calls: list[dict[str, Any]] = []
    script: dict[str, str] = {}

    async def _chat(self: Any, messages: list[dict[str, str]], **kw: Any) -> ChatResult:
        calls.append({"messages": messages, **kw})
        stage = kw.get("stage", "-")
        text = script.get(stage, script.get("*", "{}"))
        return ChatResult(
            text=text,
            model=kw.get("model") or "deepseek-v4-pro",
            prompt_tokens=10,
            completion_tokens=20,
            cost_usd=0.0001,
            finish_reason="stop",
            raw={},
        )

    monkeypatch.setattr("strategy_navigator.llm.client.LLMClient.chat", _chat)

    class Handle:
        def set(self, stage: str, text: str) -> None:
            script[stage] = text

        @property
        def calls(self) -> list[dict[str, Any]]:
            return calls

    return Handle()


@pytest.fixture
def fake_structured(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Patch generate_structured to return a scripted pydantic instance per stage."""
    responses: dict[str, Any] = {}

    async def _gen(schema: type, messages: list, *, stage: str = "-", **kw: Any) -> Any:
        if stage in responses:
            return schema.model_validate(responses[stage])
        raise AssertionError(f"no fake_structured response registered for stage {stage!r}")

    monkeypatch.setattr("strategy_navigator.llm.structured.generate_structured", _gen)
    monkeypatch.setattr("strategy_navigator.stages.domain_agent.generate_structured", _gen)
    monkeypatch.setattr("strategy_navigator.stages.idea_extraction.generate_structured", _gen)
    monkeypatch.setattr("strategy_navigator.stages.voting.child.generate_structured", _gen)
    monkeypatch.setattr("strategy_navigator.stages.custom_archetype.generate_structured", _gen)
    monkeypatch.setattr(
        "strategy_navigator.stages.foresight_consolidation.generate_structured", _gen
    )
    monkeypatch.setattr("strategy_navigator.stages.rapid_consolidation.generate_structured", _gen)

    class Handle:
        def set(self, stage: str, payload: dict) -> None:
            responses[stage] = payload

    return Handle()


@pytest.fixture
def fake_search(monkeypatch: pytest.MonkeyPatch) -> None:
    from strategy_navigator.tools.search import SearchHit

    async def _search(query: str, *, top_k: int = 5) -> list[SearchHit]:
        return [SearchHit(title=f"hit for {query}", url="https://example.com/x", snippet="...")]

    monkeypatch.setattr("strategy_navigator.stages.idea_extraction.jina_search", _search)


@pytest.fixture
def sample_project() -> dict[str, Any]:
    return {
        "projectId": 42,
        "projectName": "Grid Modernisation",
        "projectDescription": "Regional utility upgrading its distribution grid.",
        "clientOrganization": "NorthGrid",
        "clientContext": "Regulated utility, 2.1M customers.",
        "reportProfileForClient": "Board-level strategy brief",
        "timeLines": "18 months",
        "projectIntent": "De-risk the capex programme",
        "stakeholders": ["Regulator", "Operations", "Customers"],
        "documents": [],
    }
