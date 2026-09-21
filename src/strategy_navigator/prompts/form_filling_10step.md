<!--
Stage: form_filling_10step      registry refs: form_filling_10step.step_1 .. step_10
n8n workflow: "10 step form filling (3).json" (308 nodes — the largest)

Each step is its own MongoDB prompt_list template (NOT in the n8n export):
  step_1 -> promptId "3_1"  (node "AI Agent")
  step_2 -> promptId "3_2"  (node "AI Agent1")
  ...
  step_10 -> promptId "3_10" (node "AI Agent9")
  -> `strategy-navigator prompts pull`  →  prompts/_mongo/3_1.md .. 3_10.md

Variable contract (Set nodes "Step1Prompt" .. "Step10Prompt"):
  ${project_name} ${project_description} ${client_org} ${client_context}
  ${report_profile} ${project_stakeholders}
  ${agent_name} ${agent_designation} ${agent_description}
  (step 1 also: ${project_timeline})

Also in this workflow, INLINE (kept in prompts/reference/form_filling_10step.inline.md):
  - "Basic LLM Chain" x4  = the generic summariser (_shared.summarizer)
  - "Format Agent (s5..s9)" = structure-only JSON repair per step
  - "QC 1..6" + "Format Revised Agent" = the strategic-foresight report QC panel
    (shared with Report Render)

Stage NOT yet ported (StubStage). No local drafts — these must be pulled.
-->

=== _pending ===
Steps 1-10 are Mongo promptId 3_1..3_10. Run `strategy-navigator prompts pull`.
Format-repair and QC prompts are in prompts/reference/form_filling_10step.inline.md.
