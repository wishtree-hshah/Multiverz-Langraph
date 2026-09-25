# ADR 0003 — Keep the LiteLLM gateway (single instance)

Status: accepted · 2026-09-02

## Context

We run up to 14 concurrent workers (short 4 + long 6 + retry 4), each making LLM
calls to DeepSeek via OpenRouter. We need coordinated rpm/tpm limiting and
provider cooldown across all of them, plus model fallback and cost tracking.

An in-process limiter can't coordinate across worker processes. Options:
1. one LiteLLM instance in front of everything (its router state is the shared limiter)
2. build a Postgres/Redis token-bucket limiter ourselves
3. call OpenRouter directly and rely on `429` + backoff

## Decision

Keep **one** LiteLLM container (carried over from `challenges-n8n`), pointed at by
`SN_LLM_BASE_URL`. With a single instance, LiteLLM's in-memory router state
(rpm/tpm counters, cooldowns) is effectively shared across every worker — no
Redis needed for LiteLLM either.

It also gives: config-driven model swap (Anthropic models sit commented in
`litellm-config.yaml`, ready to enable), `drop_params` normalisation, and a spend
dashboard.

The app keeps its own thin layer on top (`llm/client.py`): tenacity retry,
app-level `default→fast` fallback, per-model `asyncio.Semaphore` backstop, token
accounting into `sn_token_usage`.

## Reversibility

Dropping LiteLLM is a config change, not a code change:

```
SN_LLM_BASE_URL=https://openrouter.ai/api/v1
SN_LLM_API_KEY=sk-or-v1-...
SN_LLM_DEFAULT_MODEL=openrouter/deepseek/deepseek-v4-pro
SN_LLM_FAST_MODEL=openrouter/deepseek/deepseek-v4-flash-0731
```

You then lose only cross-worker coordinated limiting (fall back to `429` +
backoff, which `llm/client.py` already handles). Acceptable for a single-worker
deployment; not recommended for the multi-lane one.

## Consequences

+ One shared limiter with zero extra code.
+ Model routing/fallback/cost stay in YAML.
− One more container (small, stateless-ish).
− A second LiteLLM replica would need Redis for shared router state — so we run
  exactly one and scale the workers instead.
