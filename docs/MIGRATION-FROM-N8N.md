# Migrating a workflow off n8n

Ported so far: `domain_agent`, `idea_extraction`, `voting`, `custom_archetype`,
`foresight_consolidation`, `rapid_consolidation`, `report_render`,
`capstone_substrate`. Everything else is a
`StubStage` that raises `StageNotImplementedError` (→ dead-letter, alert) so a
misrouted trigger is loud, not silent.

## The n8n → LangGraph mapping

| n8n | here |
|---|---|
| Webhook node | `POST /webhooks/trigger` + `payload_adapter.adapt()` |
| `Set` / `Code` node (data shaping) | plain Python in a stage node |
| `lmChatOpenRouter` + `Agent` + `outputParserStructured` | `generate_structured(Schema, messages, stage=…)` |
| `chainLlm` (freeform text) | `LLMClient.chat(...)` |
| `jinaAiTool` / `httpRequestTool` (search) | `tools.search.jina_search` / `jina_read` (Postgres-cached) |
| `extractFromFile` + S3 | `tools.documents.extract_document_text` |
| `mongoDb` node (intermediate state) | graph state — nothing to persist |
| `mongoDb` node (final artifact) | Postgres `JSONB` (or the callback body) |
| `splitInBatches` + `executeWorkflow` (fan-out) | `Send` in a conditional edge (see `stages/voting`) |
| `Merge` / `Aggregate` | a join node reading `state["partials"]` |
| `Wait` for human input | `interrupt(payload)` → run parks `waiting_human` |
| `switch` / `if` | `add_conditional_edges` |
| Error Harvest workflow | the queue task's `except` → `sn_dead_letter` + `run.dead` log |
| Token Counter workflow | automatic — every `llm.chat` writes `sn_token_usage` |
| Prompt inline in the agent node | `prompts/<workflow>.md` block, `registry` `source=INLINE` |
| Prompt fetched from Mongo `prompt_list` at runtime | `prompts/_mongo/<promptId>.md` via `strategy-navigator prompts pull` |

## Step by step

### 1. Contracts

Look at the backend DTO for the workflow's payload and callback:
`challenges-backend/src/components/n8n/dto/webhook/<name>-webhook.dto.ts`.
Add/extend the matching Pydantic models in `schemas/<workflow>.py`
(`CamelModel` handles the camelCase ↔ snake_case).

### 2. Payload adapter

Add or refine the branch in `api/payload_adapter.py` that turns the backend's
flat payload into your nested request dict. Add a test in
`tests/unit/test_payload_adapter.py`.

### 3. Prompts

There are **two** places an n8n prompt can live — check
`strategy_navigator.prompts.registry` for the workflow first, it already records
which:

**a. Mongo-backed** (`domain_agent`, `idea_extraction`, `voting`,
`foresight_consolidation`, `rapid_consolidation`, `form_filling_10step`). The
agent node is `text = {{ $json.prompt }}` and n8n loads the template from MongoDB
`prompt_list` by `promptId` at runtime. It is **not in the export**. Export it:

```bash
strategy-navigator prompts pull --mongo-url mongodb://HOST:27017 --db n8n
# or, without Mongo access:
strategy-navigator prompts pull --from-backend --backend-url https://api... --token "$JWT"
strategy-navigator prompts audit     # see every ref and what it resolves to
```

Files land in `prompts/_mongo/<promptId>.md` (commit them). Until then the stage
runs off the **local draft** block in `prompts/<workflow>.md` (logged
`prompt.using_local_draft`). In the stage, call
`render_prompt("<workflow>.<ref>", **bindings.build(project, agent=agent, ...))`.

**b. Inline** (`report_render`, `capstone_substrate`, `custom_archetype`, the
summariser). The full text is in the node and checked in verbatim under
`prompts/reference/<workflow>.inline.md`. When porting, move each block into
`prompts/<workflow>.md`, translate the n8n expression fragments
(`{{ $json.nodeXInput.toJsonString() }}`, leading `=`) to Jinja fed from graph
state, and add a `registry.PromptSpec(source=INLINE)` row.

```bash
# see every prompt-ish string in an export:
python - <<'PY'
import json
d = json.load(open("../challenges-n8n/Report Render (3).json"))
for n in d["nodes"]:
    p = n.get("parameters", {})
    for k in ("text", "jsCode", "pythonCode"):
        if isinstance(p.get(k), str) and len(p[k]) > 80:
            print("="*30, n["name"], k); print(p[k][:4000])
PY
```

### 4. The graph

Create `stages/<workflow>.py` with one node per meaningful n8n step and a
`build()` that wires them. Keep nodes small and single-purpose — that is the
whole point of leaving n8n. Use:

* `@stage_node("name")` on every node (spans, logs, timing for free)
* `get_request(state, MyRequest)` for typed input
* `put_artifact("key", value)` / `put_result(callback_model)` for output
* `interrupt(payload)` where n8n had a `Wait` for the user

For fan-out, copy the pattern in `stages/voting/__init__.py`
(`add_conditional_edges("plan", fan_out, ["child_node"])` returning `Send`s).

### 5. Register + callback path

* Swap the entry in `stages/__init__._REGISTRY` from `StubStage(...)` to `build`.
* Confirm the callback path in `callbacks/client._DEFAULT_PATH` matches the
  backend's controller (or rely on the `callbackUrl` in the payload).
* If the backend expects a bare object rather than `[obj]`, add the workflow to
  `callbacks/client._BARE_OBJECT`.

### 6. Tests

* `tests/stages/test_<workflow>.py` — compile `build()` with
  `MemorySaver()` and drive it with `fake_structured` / `fake_chat` /
  `fake_search` fixtures. Assert the callback body shape.
* Add a row to `evals/datasets/sample_projects.jsonl` and an assertion in
  `evals/run_evals.py` if output quality matters.

### 7. Cut over

Point the backend's `N8N_WEBHOOK_<WORKFLOW>_URL` at
`https://<this-service>/webhooks/trigger`. Roll back by pointing it at n8n again
— nothing else changes. Run both in parallel on a fraction of traffic first if
you want; `run_id` idempotency makes double-triggers safe.

## Porting order (recommended)

1. ~~**`custom_archetype`** — tiny (10 nodes).~~ ✅ ported.
2. ~~**`foresight_consolidation`**~~ ✅ ported. ~~**`rapid_consolidation`**~~ ✅ ported.
3. ~~**`report_render`** — worst offender (114 nodes, 100 KB of Code-node JS).~~
   ✅ ported. Turned out to be an 18-prompt pipeline with a two-pass QC-gate
   loop (6 critics → revision agent → 3 critics re-run → scorecard/gate), not
   the linear flow the export's node count alone suggested. Ported at full
   fidelity — see `stages/report_render.py`'s module docstring for the
   node-by-node trace, including the two documented scope cuts (short/batch
   section-generation path only, no automatic mechanical-audit retry loop —
   n8n computes but never wires one either).
4. ~~**`capstone_substrate`**~~ ✅ ported. Turned out to have as much (maybe
   more) load-bearing logic in its ~18 deterministic Code nodes as in its 13
   LLM calls — fact-citation repair via number-matching, entity-consolidation
   reconstruction, investment rollup, and the whole substrate assembly and
   referential-integrity check are pure Python ports with no LLM involved.
   See `stages/capstone_substrate.py`'s module docstring for the trace and
   two documented deliberate fixes over gaps in the actual n8n wiring.
5. **`form_filling_10step`** — the 308-node monster, last, one step per node.
6. `strategy_form_idea_generation`, `strategic_foresight_report` — no n8n export
   exists for either (checked all of `challenges-n8n/`); left as `StubStage`
   until source material shows up.
