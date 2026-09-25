# `reference/` — verbatim inline prompts from n8n (not loaded at runtime)

Some n8n workflows keep their prompt text **inline** in the
`@n8n/n8n-nodes-langchain.agent` node rather than fetching it from Mongo. Those
workflows are not yet ported, so their prompts are parked here verbatim as the
source of truth to port from.

| file | n8n workflow | contents |
|---|---|---|
| `report_render.inline.md` | Report Render (3).json | Node 12/13/15/16/19, EDITORIAL, QC 1-7, QC C1 |
| `capstone_substrate.inline.md` | Strategy Navigator Capstone Pipeline (4).json | Node 2-11b consolidation agents |
| `form_filling_10step.inline.md` | 10 step form filling (3).json | Format-repair agents (s5-s9), QC 1-6, summariser — the step prompts themselves are Mongo `3_1`..`3_10` |

When porting one of these stages:

1. Move each block into `../<stage>.md` as a named block (`=== node_12 ===` etc.).
2. Replace the n8n expression fragments (`{{ $json.node12Input.toJsonString() }}`,
   leading `=`, `JSON.stringify(...)`) with Jinja variables fed from graph state.
3. Add a `registry.PromptSpec` entry with `source=INLINE`.
4. Delete the corresponding block from this folder once it is live.

Nothing in this folder is imported by `strategy_navigator.prompts`.
