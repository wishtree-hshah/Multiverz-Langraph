# Stage evals

Cheap, deterministic-ish quality gates for stage output — the thing you cannot do
in n8n. Not a benchmark; a regression net so you can change a prompt or swap a
model and see if quality moved.

```bash
make eval                     # or: uv run strategy-navigator eval
```

Needs a reachable LLM gateway (`SN_LLM_*`). Reads
`datasets/sample_projects.jsonl`, runs each ported stage graph with an in-memory
checkpointer, and asserts structural + light semantic properties (counts,
non-empty fields, schema validity, no placeholder text, category sanity).

Add a case: append a line to `sample_projects.jsonl`. Add a check: extend the
per-stage function in `run_evals.py`.
