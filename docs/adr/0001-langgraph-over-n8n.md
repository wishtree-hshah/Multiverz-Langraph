# ADR 0001 — LangGraph instead of n8n for the pipeline

Status: accepted · 2026-09-02

## Context

The Strategy Navigator pipeline runs in `challenges-n8n` as ~900 nodes across 14
workflows: ~230 KB of hand-written JS in `Code` nodes (one node is 50 KB),
~100 LangChain agent nodes, `outputParserStructured` everywhere, Mongo for
state-passing, Redis for the queue, webhook-chained sub-workflows, parent/child
voting via `executeWorkflow`, a 6-hour execution timeout.

At that size n8n's benefit (visual clarity) is gone while its costs remain: no
unit tests, no meaningful diffs, no local step debugging, no typing, refactors
are manual node surgery, credentials welded to the encryption key.

The workload is a **workflow** (fixed DAG, constrained steps, human gates), not
an autonomous multi-agent system — which rules out CrewAI/AutoGen-style
frameworks and points at a graph orchestrator.

## Decision

Rebuild the pipeline as LangGraph state graphs in a Python service. Keep the
LiteLLM gateway. Replace n8n's Redis queue and Mongo with Postgres.

LangGraph specifically (over Temporal, Pydantic-AI-alone, Mastra):

* graph model matches the existing "nodes and edges" mental model
* durable execution + Postgres checkpointing → a retry resumes, not restarts
* first-class `interrupt()` for the human-decision points
* model-agnostic — the LiteLLM/DeepSeek setup is unchanged
* 1.0 GA, active, strongest HITL + durability story of the options

Temporal remains a future option to wrap LangGraph invocations if durability
guarantees ever need to be stronger; not needed on day one.

## Consequences

+ Every stage is unit-testable with fake LLM fixtures.
+ Prompts become versioned files, reviewable by non-engineers.
+ Real concurrency control, token accounting, tracing.
+ One datastore to operate and back up.
− Python service to run alongside the NestJS backend (new deployable).
− ~10 s/run checkpointing overhead (irrelevant at our runtimes).
− The 308-node `form_filling_10step` is a real porting effort (done last).

## Migration

Incremental. The service is a drop-in for the n8n webhook layer; workflows cut
over one env var at a time and roll back the same way. Un-ported workflows are
loud stubs. See [../MIGRATION-FROM-N8N.md](../MIGRATION-FROM-N8N.md).
