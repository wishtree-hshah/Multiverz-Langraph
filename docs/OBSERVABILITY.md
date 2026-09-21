# Observability

## Logs

`structlog`. Console-pretty locally (`SN_LOG_JSON=false`), one JSON object per
line in staging/prod (`SN_LOG_JSON=true`). Every line inside a run carries
`run_id`, `session_id`, `workflow`, and (in the worker) `attempt`, because those
are bound into a `contextvar` by `bind_context()` at the run boundary — you never
pass a logger around.

### Event vocabulary

| event | where | key fields |
|---|---|---|
| `http.request` | API middleware | method, path, status, ms |
| `run.enqueued` | queue | queue, lane, priority |
| `graph.start` / `graph.done` | runner | cost_usd |
| `stage.start` / `stage.end` | every node | stage, ms |
| `llm.chat` (span) / `llm.usage` | LLM client | model, stage, prompt_tokens, completion_tokens, cost_usd |
| `llm.fallback` | LLM client | primary, fallback, error |
| `structured.repair` | structured output | stage, attempt, error |
| `search.cache_hit` / `search.done` | Jina tool | op, query, hits |
| `run.retry_scheduled` | queue | attempt, error |
| `run.dead` | queue | error_type, error, + traceback via exc_info |
| `callback.delivered` | callback client | workflow, url, status |

**Alert on `run.dead`.** That is the only "someone must look" event.

### Useful queries (JSON logs → your log store)

```
event="run.dead"                                   # failures needing a human
event="llm.fallback"                               # gateway degradation
event="structured.repair" attempt>=1               # a prompt/schema drifting
event="stage.end" ms>120000                        # slow nodes
event="run.retry_scheduled" | count by workflow    # which workflow is flaky
```

## Traces (optional)

Set `SN_OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4318`. Without it, every
tracing call is a no-op — zero overhead.

Span tree for one run:

```
workflow.report_render
├─ stage.render_planning
│  └─ llm.chat  (llm.model, llm.stage)
├─ stage.section_generation
│  ├─ tool.jina.read
│  └─ llm.chat
├─ stage.audit
│  └─ llm.chat
└─ callback.report_render
```

FastAPI and httpx are auto-instrumented when tracing is on.

## Token / cost

Every model call writes a `sn_token_usage` row (run, session, workflow, stage,
model, tokens, `cost_usd` from `litellm.completion_cost`). This replaces the n8n
"Token Counter" workflow.

```
GET /admin/token-usage                       # grouped by workflow + model
GET /admin/token-usage?session_id=demo-1     # one run
```

```sql
-- spend per workflow, last 24h
SELECT workflow, SUM(cost_usd) usd, SUM(total_tokens) toks
FROM sn_token_usage WHERE created_at > now() - interval '24 hours'
GROUP BY workflow ORDER BY usd DESC;
```

The callback body sent to the backend also carries a `tokenUsage` array in the
same per-model shape the backend's `TokenUsageByModelService` already normalises.

## Run state

```
GET /runs/{run_id}          → status, attempts, interrupt payload, result
GET /admin/dead-letter      → unreplayed failures
```

```sql
-- runs in flight right now
SELECT workflow, status, count(*) FROM sn_run
WHERE status IN ('queued','running','waiting_human') GROUP BY 1,2;
```

## LiteLLM

`http://localhost:4010` (SSH-tunnel only in prod) exposes LiteLLM's own
`/metrics` and spend logs — the gateway-side view of rpm/tpm usage and provider
cooldowns.
