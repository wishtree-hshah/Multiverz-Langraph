<!--
Stage: report_render
n8n workflow: "Report Render (3).json" (114 nodes, ~18 agents)

Prompt SOURCE: INLINE. Every node prompt is in the workflow and checked in
verbatim at prompts/reference/report_render.inline.md:
  Node 12 Engagement-Gap Detection      QC 1 Traceability Auditor
  Node 13 External Search & Options      QC 2 Coherence Checker
  Node 15 Render Planning                QC 3 Reader Persona Panel
  Node 16 Fact-Currency Search Planning  QC 4 Red Team Critic
  Node 19 Section Generation             QC 5 Surprise & Genericity Scorer
  EDITORIAL (section editor)             QC 6 Revision Agent
                                        QC 7 Scorecard & Gate
                                        QC C1 Render Conformance & Provenance

Stage NOT yet ported. When porting: lift each block into this file as
`=== node_15 ===`, `=== qc_1 ===` etc., wire the `{{ $json.node*Input }}` inputs
from graph state, and add registry rows with source=INLINE.
-->

=== _pending ===
See prompts/reference/report_render.inline.md for the full verbatim prompts.
