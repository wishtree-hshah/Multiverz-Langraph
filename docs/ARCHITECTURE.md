# Architecture

## 1. Where this sits

```
┌────────────────────┐      {workflow_name, payload}       ┌──────────────────────────┐
│ challenges-backend │ ─────────────HTTP POST────────────▶ │ strategy-navigator (this) │
│  (NestJS / MySQL)  │ ◀────────async callback POST─────── │  FastAPI + LangGraph      │
└────────────────────┘                                     └──────────────────────────┘
```

The backend is unchanged. Its per-workflow `N8N_WEBHOOK_*_URL` env vars point at
`POST /webhooks/trigger` here instead of at n8n. The callback contract
(single-element array envelope, `sessionId` correlation, `tokenUsage`,
`errorMessage`) is preserved by `strategy_navigator/callbacks/client.py`.

## 2. Process types

| Process | Command | Scales on |
|---|---|---|
| API | `strategy-navigator serve` | request volume (stateless) |
| Short worker | `strategy-navigator worker --lane short` | short-lane backlog |
| Long worker | `strategy-navigator worker --lane long` | long-lane backlog |
| Retry worker | `strategy-navigator worker --lane retry` | retry backlog |
| Migrator | `strategy-navigator db upgrade` | one-shot on deploy |

All five are the same Docker image; the subcommand picks the role.

## 3. Data stores

| Store | Owner | Contents |
|---|---|---|
| Postgres `checkpoints*` | LangGraph | per-run graph state, one row per node completion |
| Postgres `procrastinate_*` | procrastinate | the job queue |
| Postgres `sn_run` | this app | run lifecycle, attempts, callback URL, interrupt payload, result |
| Postgres `sn_search_cache` | this app | Jina results by query hash, TTL'd |
| Postgres `sn_dead_letter` | this app | runs that exhausted `SN_RUN_MAX_ATTEMPTS` |
| Postgres `sn_token_usage` | this app | per-call model spend |
| LiteLLM (in-memory) | LiteLLM | rpm/tpm counters, provider cooldown — shared across all workers because there is one instance |

No Redis. No Mongo. See [adr/0002](adr/0002-postgres-queue-over-redis.md).

## 4. Request lifecycle

```
POST /webhooks/trigger
  │  validate envelope → resolve Workflow → payload_adapter.adapt()
  │  run_id = "<workflow>:<sessionId>"     (idempotent — re-trigger is a no-op)
  ▼
enqueue_run()
  │  INSERT sn_run (status=queued)         [ON CONFLICT DO NOTHING]
  │  procrastinate defer → queue sn_short | sn_long, priority 0
  ▼  202 Accepted {run_id, lane, ported}
  ┈┈┈ (async) ┈┈┈
worker picks job
  │  sn_run → running, attempts=N
  │  run_workflow_graph():
  │    open Postgres checkpointer (thread_id = run_id)
  │    build compiled graph for the workflow
  │    astream(initial_state | Command(resume=…))
  │      each node: span + structured logs + token accounting
  │    ├─ interrupt()  → sn_run.status = waiting_human, store payload, RETURN
  │    └─ END          → state["result"] is the callback body
  │  sn_run → succeeded, result stored
  │  callbacks.client.post_callback() → backend
  ▼
```

Failure paths in §5 of [QUEUES-AND-LANES.md](QUEUES-AND-LANES.md).

## 5. The graph state

One `TypedDict` (`graph/state.py`) is shared by every workflow:

| key | reducer | meaning |
|---|---|---|
| `run_id`, `session_id`, `workflow`, `project_id` | — | identity, set once |
| `request` | — | the validated inbound payload (dict) |
| `artifacts` | dict merge | each stage writes its output under its own key |
| `partials` | list concat | fan-out accumulator (voting children, sections) |
| `result` | — | the finished callback body |
| `errors` | list concat | non-fatal problems collected along the way |
| `_child` | — | payload handed to one `Send`'d child node |

Stages never mutate state in place — a node returns a dict and LangGraph applies
it through the reducers. That is what makes checkpoint replay correct.

## 6. Stage anatomy

Every workflow module exposes `build() -> StateGraph`. A typical node:

```python
@stage_node("generate_personas")               # span + timing + logs
async def generate_personas(state: PipelineState) -> dict[str, Any]:
    req = get_request(state, DomainAgentRequest)          # typed inbound
    system = render("domain_agent.system", ...)           # versioned prompt
    out = await generate_structured(DomainAgentOutput, [...], stage="generate_personas")
    return put_artifact("personas", out.model_dump())     # merged into artifacts
```

`generate_structured` is the one replacement for every n8n
`outputParserStructured` node: call → parse JSON → validate against a Pydantic
model → one repair round-trip on failure → `StructuredOutputError` (transient).

## 7. LLM path

`stage → generate_structured / LLMClient.chat → litellm.acompletion → SN_LLM_BASE_URL`

* per-model `asyncio.Semaphore` (local backstop; LiteLLM is the real limiter)
* `tenacity` retry on rate-limit / 5xx / timeout, exponential backoff
* app-level fallback `default_model → fast_model` if the gateway 5xxes the chain
* `usage` → `sn_token_usage` + in-run tally → callback `tokenUsage`
* every call is an `llm.chat` span

Drop the LiteLLM container by pointing `SN_LLM_BASE_URL` at
`https://openrouter.ai/api/v1` and prefixing models with `openrouter/`.

## 8. Human-in-the-loop

The three "user decides" points in the Strategy Navigator flow (select agents,
select ideas, pick archetype) map to LangGraph `interrupt()` calls inside the
relevant graph. On interrupt the run parks as `waiting_human` with the payload
stored; the frontend reads it via `GET /runs/{run_id}` and continues with
`POST /runs/{run_id}/resume {value: …}`, which re-enqueues the run at
`PRIORITY_HUMAN_RESUME` (above fresh work, below retries). The checkpoint means
it resumes exactly where it paused.

*(None of the currently-ported stages interrupt — the machinery is in place for
the consolidation/archetype stages when they are ported.)*
