# Queues, lanes, priority, retry, dead-letter

## Lanes

Two bulkheads, mirroring `challenges-n8n` (4 short slots / 6 heavy slots), plus a
dedicated retry pool.

| Lane | Queue | Default concurrency | Workflows |
|---|---|---|---|
| short | `sn_short` | `SN_LANE_SHORT_CONCURRENCY=4` | domain_agent, idea_extraction, strategy_form_idea_generation, rapid_consolidation, foresight_consolidation, voting |
| long | `sn_long` | `SN_LANE_LONG_CONCURRENCY=6` | form_filling_10step, capstone_substrate, report_render, custom_archetype, strategic_foresight_report |
| retry | `sn_retry` | `SN_LANE_RETRY_CONCURRENCY=4` | any workflow, resumed after a failure |

A lane = one worker **deployment** subscribed to one queue with `--concurrency N`.
Scale a lane by scaling its deployment (more replicas) or raising its concurrency
env var. The lanes cannot starve each other because they are different pools
consuming different queues — the same isolation the separate Redis DBs gave n8n,
without Redis.

```
worker --lane short  →  run_worker_async(queues=["sn_short"], concurrency=4)
worker --lane long   →  run_worker_async(queues=["sn_long"],  concurrency=6)
worker --lane retry  →  run_worker_async(queues=["sn_retry"], concurrency=4)
```

## Priority

procrastinate job priority (higher runs first) within a queue:

| Constant | Value | Used for |
|---|---|---|
| `PRIORITY_FRESH` | 0 | a brand-new run |
| `PRIORITY_HUMAN_RESUME` | 50 | a run resumed at a human gate — a person is waiting |
| `PRIORITY_RETRY` | 100 | a resumed run after failure |

Because retries have their own pool, priority only matters if that pool is
momentarily saturated; then the oldest highest-priority job wins.

## Failure handling — three tiers

```
                         ┌─────────────────────────────┐
  transient inside a run │ LLM 5xx / timeout / Jina 503 │  handled by
                         │  → LLMClient tenacity retry  │  the LLM/tool client;
                         │  → node stays in its lane    │  never leaves the lane
                         └─────────────────────────────┘
                                      │ exhausted
                                      ▼
                         ┌─────────────────────────────┐
   run raises            │ TransientError / unexpected  │  queue task catches it:
   (node gave up,        │  attempt < SN_RUN_MAX_ATTEMPTS│  sn_run → failed,
    worker crashed,      │  → re-defer to sn_retry      │  re-defer at PRIORITY_RETRY,
    timeout)             │    at PRIORITY_RETRY,         │  attempt += 1
                         │    attempt += 1              │
                         │  retry worker RESUMES from    │  ← LangGraph checkpoint:
                         │  the last checkpoint          │    completed nodes are skipped
                         └─────────────────────────────┘
                                      │ attempts exhausted, or PermanentError
                                      ▼
                         ┌─────────────────────────────┐
   dead-letter           │ sn_run → dead                │  INSERT sn_dead_letter
                         │ INSERT sn_dead_letter        │  (error_type, message,
                         │ error callback to backend    │   traceback, full payload)
                         │ log "run.dead" (alert here)  │  → hook alerting on this
                         └─────────────────────────────┘
```

`PermanentError` subclasses (`InvalidPayloadError`, `UnknownWorkflowError`,
`StageNotImplementedError`) skip the retry tier and dead-letter immediately —
retrying a bad payload or a stub workflow only wastes tokens.

### Why a retry resume is cheap

A `report_render` run that dies on section 14 of 20 does **not** regenerate
sections 1–13 on retry — LangGraph's Postgres checkpointer replays the state up
to the last completed node and continues. This is why the retry pool is only 4
even though the long lane is 6: retried long runs usually have little left to do.

## Dead-letter operations

```
GET  /admin/dead-letter                 # unreplayed rows
POST /admin/dead-letter/{id}/replay     # re-enqueue with the stored payload
```

or from the shell: `python scripts/replay_dead_letter.py --workflow report_render`.

## Idempotency

`run_id = "<workflow>:<sessionId>"`. `enqueue_run` does
`INSERT ... ON CONFLICT DO NOTHING` on `sn_run`, and re-deferring the same job
key is a no-op in procrastinate. Re-triggering a workflow for a session that is
already running or done will not double-run it.

## Tuning

| Symptom | Lever |
|---|---|
| Short lane backlog growing | `SN_LANE_SHORT_CONCURRENCY` ↑ or add a `worker-short` replica |
| OpenRouter 429s under load | `SN_LLM_CONCURRENCY` ↓, or raise the model's `rpm`/`tpm` in `litellm-config.yaml` |
| Retries piling up | investigate `sn_dead_letter.error_type` distribution first; raise `SN_LANE_RETRY_CONCURRENCY` only if failures are genuinely transient |
| A long run times out repeatedly | raise `SN_DB_STATEMENT_TIMEOUT_MS` is **not** it — check `EXECUTIONS`-style per-run budget in the stage; consider splitting the graph |
