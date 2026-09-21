"""Structured generation: call the model, parse JSON, validate against a Pydantic
model, and on failure feed the validation errors back for one repair attempt.

This is the single replacement for every ``outputParserStructured`` node in the
n8n workflows. Prefer it over raw :meth:`LLMClient.chat` whenever a stage needs a
typed object back.
"""

from __future__ import annotations

import json
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from strategy_navigator.errors import StructuredOutputError
from strategy_navigator.llm.client import Message, get_llm
from strategy_navigator.logging import get_logger

log = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

_REPAIR_TEMPLATE = (
    "Your previous response did not match the required JSON schema.\n"
    "Validation errors:\n{errors}\n\n"
    "Return ONLY corrected JSON that satisfies the schema. No prose, no code fences."
)


def _extract_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        text = text.removeprefix("json").strip()
    start = text.find("{")
    start_arr = text.find("[")
    if start_arr != -1 and (start == -1 or start_arr < start):
        start = start_arr
    end = max(text.rfind("}"), text.rfind("]"))
    if start != -1 and end != -1:
        return text[start : end + 1]
    return text


async def generate_structured[T: BaseModel](
    schema: type[T],
    messages: list[Message],
    *,
    model: str | None = None,
    fast: bool = False,
    temperature: float = 0.1,
    max_tokens: int | None = None,
    stage: str = "-",
    max_repairs: int = 1,
) -> T:
    llm = get_llm()
    convo = list(messages)
    schema_json = json.dumps(schema.model_json_schema(), indent=2)
    convo.append(
        {
            "role": "system",
            "content": f"Respond with a single JSON value matching this schema:\n{schema_json}",
        }
    )

    last_error = ""
    last_raw = ""
    for attempt in range(max_repairs + 1):
        result = await llm.chat(
            convo,
            model=model,
            fast=fast,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            stage=stage,
        )
        last_raw = result.text
        try:
            payload = json.loads(_extract_json(result.text))
            return schema.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = str(exc)
            log.warning(
                "structured.repair",
                stage=stage,
                attempt=attempt,
                error=last_error[:500],
            )
            convo.append({"role": "assistant", "content": result.text})
            convo.append({"role": "user", "content": _REPAIR_TEMPLATE.format(errors=last_error)})

    raise StructuredOutputError(
        f"[{stage}] output failed schema {schema.__name__} after {max_repairs + 1} attempts: "
        f"{last_error}",
        raw=last_raw,
    )
