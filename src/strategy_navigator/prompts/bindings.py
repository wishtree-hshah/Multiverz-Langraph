"""Build the variable dict a prompt template renders against.

The n8n Set nodes substitute ``${project_name}``, ``${client_org}`` etc. straight
from the webhook payload (mostly ``JSON.stringify``-ed). We reproduce that exact
mapping here so a Mongo-exported template renders unchanged, and so our local
fallback blocks can use the same names.

Templates reference only a subset of these, but we always pass the full set: with
Jinja ``StrictUndefined`` a template that names a variable we did not supply
raises, whereas an unused key we supply is harmless.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic.alias_generators import to_camel

from strategy_navigator.schemas.common import AgentRef, ProjectContext


def _j(value: Any) -> str:
    """Mirror n8n's ``JSON.stringify`` for scalars/arrays used in prompts."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def project_vars(project: ProjectContext) -> dict[str, str]:
    stakeholders = list(project.stakeholders or [])
    timelines = project.time_lines or ""
    docs = list(project.documents or [])
    return {
        "project_name": project.project_name,
        "project_title": project.project_name,
        "client": project.client_organization,
        "client_org": project.client_organization,
        "client_organization": project.client_organization,
        "client_context": project.client_context,
        "project_description": project.project_description,
        "project_timelines": timelines,
        "project_timeline": timelines,
        "time_horizon": timelines,
        "project_stakeholders": _j(stakeholders),
        "stakeholders": ", ".join(stakeholders),
        "report_profile": project.report_profile_for_client,
        "report_style": project.report_profile_for_client,
        "project_intent": project.project_intent or "",
        "timeline": timelines,
        # documents are injected as summarised text by the ingest node; default empty
        "project_documents": "",
        "documents": _j(docs),
    }


def agent_vars(agent: AgentRef | None) -> dict[str, str]:
    if agent is None:
        return dict.fromkeys(
            (
                "agent_name",
                "agent_designation",
                "agent_description",
                "agent_type",
                "agent_stakeholder",
            ),
            "",
        )
    return {
        "agent_name": agent.name,
        "agent_designation": agent.designation or "",
        "agent_description": agent.description or "",
        "agent_type": str(agent.agent_type or ""),
        "agent_stakeholder": agent.stakeholder or "",
    }


def build(
    project: ProjectContext,
    *,
    agent: AgentRef | None = None,
    document_summary: str = "",
    **extra: Any,
) -> dict[str, Any]:
    v: dict[str, Any] = {**project_vars(project), **agent_vars(agent)}
    if document_summary:
        v["project_documents"] = document_summary
        v["documents"] = document_summary
    # n8n prompt_list templates mix snake_case and camelCase for the same field
    # (e.g. ${projectName} in the 10-step prompts, ${project_name} in domain_agent).
    # Supply both spellings so any template renders under StrictUndefined.
    for key in list(v):
        camel = to_camel(key)
        if camel != key:
            v.setdefault(camel, v[key])
    # a pre-composed block, handy for local fallback prompts
    v.setdefault("project_context", _project_context_block(v, document_summary))
    v["project"] = project
    if agent is not None:
        v["agent"] = agent
    v.update(extra)
    return v


def _project_context_block(v: dict[str, str], document_summary: str) -> str:
    lines = [
        f"PROJECT: {v['project_name']}",
        f"DESCRIPTION: {v['project_description']}",
        f"CLIENT ORGANISATION: {v['client_organization']}",
        f"CLIENT CONTEXT: {v['client_context']}",
        f"REPORT PROFILE FOR CLIENT: {v['report_profile']}",
    ]
    if v.get("project_timelines"):
        lines.append(f"TIMELINES: {v['project_timelines']}")
    if v.get("project_intent"):
        lines.append(f"PROJECT INTENT: {v['project_intent']}")
    if v.get("stakeholders"):
        lines.append(f"STAKEHOLDERS: {v['stakeholders']}")
    if document_summary:
        lines.append(f"\nBACKGROUND DOCUMENTS (summarised):\n{document_summary}")
    return "\n".join(lines)
