# Strategy Navigator — LangGraph Orchestration

Production replacement for the two n8n lanes in `../challenges-n8n`. The Strategy
Navigator pipeline (domain agent → idea generation → consolidation → foresight →
voting → capstone substrate → report render) runs as durable, testable,
code-first LangGraph workflows instead of ~900 n8n nodes.

It is a **drop-in swap for the n8n webhook layer**: `../challenges-backend`
triggers each workflow with `{ workflow_name, payload }` and receives an async
callback. This service speaks the exact same contract, so the backend does not
change — only its `N8N_WEBHOOK_*_URL` env vars repoint here.

```
challenges-backend ──HTTP {workflow_name,payload}──▶  POST /webhooks/trigger
                                                          │  (this service)
                                                          ▼
                                             procrastinate queue (Postgres)
                                          ┌──────────┬──────────┬──────────┐
                                          ▼          ▼          ▼
                                     worker-short worker-long worker-retry
                                        (4)         (6)         (4, prio)
                                          │          │          │
                                          ▼          ▼          ▼
                                   LangGraph workflow graph
                                     • checkpointer → Postgres  (resume, not restart)
                                     • interrupt()  → human gates
                                     • LLM calls    → LiteLLM → DeepSeek/OpenRouter
                                     • search       → Jina (Postgres-cached)
                                          │
                                          ▼
                              POST callback ──▶ challenges-backend
```

**Stack: Postgres + LiteLLM. No Redis, no Mongo.** Postgres runs the queue,
the LangGraph checkpoints, the app tables, and the Jina cache. One LiteLLM
instance is the cross-worker rate limiter.

---

## Quick start (local)

```bash
cp .env.example .env            # fill SN_LLM_API_KEY, OPENROUTER_KEY, SN_JINA_API_KEY
make up                         # postgres + litellm + migrate + api + 3 workers
curl localhost:8000/readyz
```

Trigger a workflow the way the backend does:

```bash
curl -s localhost:8000/webhooks/trigger -H 'content-type: application/json' -d '{
  "workflow_name": "Domain-specific-agent-generation",
  "payload": {
    "sessionId": "demo-1", "projectId": 1,
    "projectName": "Grid Modernisation", "projectDescription": "…",
    "clientOrganization": "NorthGrid", "clientContext": "…",
    "reportProfileForClient": "Board brief", "stakeholders": ["Regulator"]
  }
}' | jq
```

Watch it run: `make logs`. Inspect: `GET /runs/domain_agent:demo-1`.

## Without Docker

```bash
make install          # uv venv + deps
# point SN_DATABASE_URL at a Postgres you control, then:
make migrate          # alembic + procrastinate + checkpointer schema
make serve            # API on :8000
make worker-short     # in another shell
make worker-long
make worker-retry
```

## Repository layout

| Path | What |
|---|---|
| `src/strategy_navigator/config.py` | all env-driven settings (`SN_*`) |
| `src/strategy_navigator/logging.py` | structlog setup + correlation-id context |
| `src/strategy_navigator/observability/` | optional OpenTelemetry tracing |
| `src/strategy_navigator/llm/` | LiteLLM client, structured-output helper, token accounting, per-model concurrency |
| `src/strategy_navigator/tools/` | Jina search/reader (Postgres-cached), document ingestion |
| `src/strategy_navigator/prompts/` | one `.md` per stage (Jinja2), git-versioned |
| `src/strategy_navigator/schemas/` | Pydantic I/O models — one per stage, camelCase-compatible with the backend |
| `src/strategy_navigator/graph/` | shared `PipelineState`, Postgres checkpointer, run/resume runner |
| `src/strategy_navigator/stages/` | one module per workflow (`domain_agent`, `idea_extraction`, `voting/` ported; rest are stubs) |
| `src/strategy_navigator/queue/` | procrastinate app, lane↔queue mapping, the `run_workflow` task + retry routing |
| `src/strategy_navigator/callbacks/` | POST results back to challenges-backend |
| `src/strategy_navigator/api/` | FastAPI: `/webhooks/*`, `/runs/*`, `/admin/*`, health |
| `migrations/` | Alembic (app tables only) |
| `docs/` | architecture, migration guide, queue design, observability, ADRs |
| `evals/` | per-stage output-quality checks |

## Porting status

`strategy-navigator workflows` prints the table. Ported: `domain_agent`,
`idea_extraction`, `voting`, `custom_archetype`, `foresight_consolidation`,
`rapid_consolidation`, `report_render`, `capstone_substrate`,
`form_filling_10step`. The rest raise `StageNotImplementedError` (→
dead-letter, alert) until ported — see [docs/MIGRATION-FROM-N8N.md](docs/MIGRATION-FROM-N8N.md).

## Testing

```bash
make test        # unit + stage graphs, no external services
make test-int    # integration (needs Postgres + LiteLLM)
make lint        # ruff + mypy
```

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — components, data flow, state model
- [docs/QUEUES-AND-LANES.md](docs/QUEUES-AND-LANES.md) — lanes, priority, retry, dead-letter
- [docs/MIGRATION-FROM-N8N.md](docs/MIGRATION-FROM-N8N.md) — how to port a workflow
- [docs/OBSERVABILITY.md](docs/OBSERVABILITY.md) — logs, traces, token spend
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — EC2 / compose, scaling lanes
- [docs/adr/](docs/adr/) — why LangGraph, why Postgres queue, why LiteLLM
