# ADR 0002 — Postgres-backed queue (procrastinate), no Redis

Status: accepted · 2026-09-02

## Context

We need: named queues (short/long/retry), per-lane concurrency caps, job
priority, retry with re-routing to a dedicated lane, and durability. n8n used
Redis (separate DBs per lane) for this.

We already must run Postgres (LangGraph checkpointer + app tables). Adding Redis
means a second stateful service to operate, back up, and secure.

## Decision

Use **procrastinate** (Postgres-backed job queue) for the outer scheduler:

* queues `sn_short` / `sn_long` / `sn_retry`, one worker deployment per lane
* concurrency is the worker's `--concurrency`; lanes are isolated because they
  are different pools on different queues
* `priority` orders jobs within a queue (retries at 100, human-resume at 50)
* retry routing is explicit: the task catches the failure and
  `defer`s a new job onto `sn_retry` — procrastinate's built-in retry can't
  change queue, and we want the dedicated pool anyway

Redis is not added. The only other thing it would have done — a cross-worker LLM
rate limiter — is handled by running a single LiteLLM instance (ADR 0003).

## Alternatives

* **Celery + Redis/RabbitMQ** — heavier, another broker, priority support is
  awkward. No.
* **arq (Redis)** — nice and async but needs Redis and has weak priority.
* **Temporal** — excellent durability but a large operational component for what
  is, today, "run a graph with lane limits". Revisit if guarantees must harden.
* **Hand-rolled `asyncio` in the API process** — no durability, no back-pressure
  across replicas, lose everything on a restart. No.

## Consequences

+ One datastore. One backup. One thing to secure.
+ Queue state is inspectable with SQL alongside run history.
+ `LISTEN/NOTIFY` gives low-latency job pickup without polling.
− procrastinate is smaller than Celery's ecosystem (acceptable — our needs are small).
− Very high job throughput (>hundreds/sec) would eventually want a real broker;
  we are nowhere near that (runs are minutes-to-hours).
