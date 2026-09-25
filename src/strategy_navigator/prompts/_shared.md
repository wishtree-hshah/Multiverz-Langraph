<!--
Shared blocks used across stages.

- project_context : convenience block; NOT what n8n does (n8n substitutes
  ${project_name} etc. individually — see prompts/bindings.py). Used by local draft
  prompts and by stages that want a single context string.
- summarizer     : registry ref "_shared.summarizer", source INLINE. Verbatim
  copy of the "Basic LLM Chain" node in "Domain Specific Agent (1).json"
  (identical node also in 10-step form filling). Runs on each background doc
  before the stage prompt sees it.
-->

=== project_context ===
PROJECT: {{ project_name }}
DESCRIPTION: {{ project_description }}
CLIENT ORGANISATION: {{ client_organization }}
CLIENT CONTEXT: {{ client_context }}
REPORT PROFILE FOR CLIENT: {{ report_profile }}
{% if project_timelines %}TIMELINES: {{ project_timelines }}{% endif %}
{% if project_intent %}PROJECT INTENT: {{ project_intent }}{% endif %}
{% if stakeholders %}STAKEHOLDERS: {{ stakeholders }}{% endif %}
{% if project_documents %}

BACKGROUND DOCUMENTS (summarised):
{{ project_documents }}
{% endif %}

=== summarizer ===
### **General Summarization Prompt (No Restrictions)**

You are an intelligent summarization assistant.

Read the following content carefully and produce a **clear, coherent, and meaningful summary**.

The summary should:

* Capture the **main ideas and important details**
* Remove redundancy, noise, and irrelevant information
* Preserve the **original intent and context**
* Use **simple, natural language**
* Flow logically without forcing length, format, or structure

Do not add new information or personal opinions.

**Content to summarize:**
{{ content }}
