import pytest
from pydantic import BaseModel

from strategy_navigator.errors import StructuredOutputError
from strategy_navigator.llm.structured import _extract_json, generate_structured


class Foo(BaseModel):
    a: int
    b: str


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"a": 1, "b": "x"}', '{"a": 1, "b": "x"}'),
        ('```json\n{"a": 1, "b": "x"}\n```', '{"a": 1, "b": "x"}'),
        ('here you go: {"a": 1, "b": "x"} done', '{"a": 1, "b": "x"}'),
        ('[{"a": 1}]', '[{"a": 1}]'),
    ],
)
def test_extract_json(raw, expected):
    assert _extract_json(raw) == expected


async def test_generate_structured_happy_path(fake_chat):
    fake_chat.set("t", '{"a": 3, "b": "ok"}')
    out = await generate_structured(Foo, [{"role": "user", "content": "go"}], stage="t")
    assert out == Foo(a=3, b="ok")


async def test_generate_structured_repairs_once(fake_chat, monkeypatch):
    seq = iter(['{"a": "not-int"}', '{"a": 5, "b": "fixed"}'])

    async def _chat(self, messages, **kw):
        from strategy_navigator.llm.client import ChatResult

        return ChatResult(
            text=next(seq),
            model="m",
            prompt_tokens=1,
            completion_tokens=1,
            cost_usd=0.0,
            finish_reason="stop",
            raw={},
        )

    monkeypatch.setattr("strategy_navigator.llm.client.LLMClient.chat", _chat)
    out = await generate_structured(Foo, [{"role": "user", "content": "go"}], stage="t")
    assert out == Foo(a=5, b="fixed")


async def test_generate_structured_gives_up(fake_chat):
    fake_chat.set("t", "not json at all")
    with pytest.raises(StructuredOutputError):
        await generate_structured(
            Foo, [{"role": "user", "content": "go"}], stage="t", max_repairs=1
        )
