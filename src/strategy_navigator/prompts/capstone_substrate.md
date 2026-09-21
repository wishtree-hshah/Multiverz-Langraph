<!--
Stage: capstone_substrate
n8n workflow: "Strategy Navigator Capstone Pipeline (4).json" (78 nodes)

Prompt SOURCE: INLINE. Every node prompt is carried in the workflow and checked
in verbatim at prompts/reference/capstone_substrate.inline.md:
  Node 2  Citation Resolution          Node 7   Recommendation Consolidation
  Node 3  Facts Register               Node 7b  Preferred Future & Provocations
  Node 4a Entity Consolidation (x3:    Node 7c  Investment Sizing (web search)
          signals / uncertainties /    Node 9   Stakeholder Lensing
          best practices)              Node 11b Substrate Review
  Node 4b Relational Binding
  Node 5  Trend Clustering
  Node 6  Foresight-to-Action Map

Stage NOT yet ported. When porting: lift each block from the reference file into
this file as `=== node_2 ===` etc., replace `{{ $json.*Input.toJsonString() }}`
with Jinja fed from graph state, and add registry.PromptSpec(source=INLINE) rows.
-->

=== _pending ===
See prompts/reference/capstone_substrate.inline.md for the full verbatim prompts.
