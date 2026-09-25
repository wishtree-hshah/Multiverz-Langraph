# `_mongo/` — prompt templates exported from the n8n MongoDB

The n8n workflows do **not** carry their operative prompt text. Each
`@n8n/n8n-nodes-langchain.agent` node is `text = {{ $json.prompt }}`, and the
template string is fetched at runtime from MongoDB (`prompt_list` collection,
keyed by `promptId`). Only `promptId` and the `${var}` contract survive in the
workflow export — see `strategy_navigator.prompts.registry`.

**Status:** all 30 templates the pipeline references are committed here, from a
manual `admin.prompt_list` export (2026-09-09). `1.md` and `2.md` (domain_agent,
idea_extraction) are byte-exact and rendered at runtime. The `5_*` lens prompts,
`3_*` steps, `4`, `6`, `10 step`-appendix-heavy prompts are checked in as
faithful reference (some long shared boilerplate elided, marked `[NOTE: ...]`) —
re-run the pull below against the live Mongo to replace them with byte-exact
copies. `8`, `consolidation_a/b/c`, `document_ingestion_prompt` are near-verbatim.

## Refreshing / verifying this folder

```bash
# from Mongo directly
strategy-navigator prompts pull --mongo-url mongodb://HOST:27017 --db n8n

# or via the challenges-backend prompt API (GET /n8n/prompts)
strategy-navigator prompts pull --from-backend --backend-url https://api.example --token "$JWT"

# CI guard — non-zero exit if a needed template is not exported
strategy-navigator prompts pull --check
```

Each file is `<promptId>.md` with a small front-matter header and the verbatim
template body. The loader rewrites `${var}` → Jinja `{{ var }}` on read
(`strategy_navigator.prompts.__init__._mongo_template`), and
`strategy_navigator.prompts.bindings.build()` supplies every variable name the n8n
Set nodes substitute.

## Needed templates

| promptId | stage | n8n workflow |
|---|---|---|
| `1` | domain_agent | Domain Specific Agent |
| `2` | idea_extraction | Agent Idea Extraction with Project |
| `document_ingestion_prompt` | idea_extraction (doc pre-pass) | Agent Idea Extraction with Project |
| `5_innovation_agent_system_prompt` … `5_geo_political_agent_system_prompt` | voting (9 lens agents) | Voting Agent (Child) |
| `5_contextual_agent_system_prompt` | voting (contextual agent) | Voting Agent (Child) |
| `8` | foresight_consolidation | Foresight Consolidation Agent |
| `consolidation_a` / `consolidation_b` / `consolidation_c` | rapid_consolidation | Rapid Insight - Consolidation Agent |
| `3_1` … `3_10` | form_filling_10step (steps 1-10) | 10 step form filling |

## Do these get committed?

Yes — they are the production prompts and belong under version control so changes
are reviewable. They contain no secrets. Re-run `pull` after ops edits a prompt
in the n8n UI, and commit the diff.

Until a template is exported, `render_prompt()` falls back to the stage's local
**draft** block in `../<stage>.md` (logged as `prompt.using_local_draft`) or, for
stages with no draft, raises `PromptNotExportedError`.
