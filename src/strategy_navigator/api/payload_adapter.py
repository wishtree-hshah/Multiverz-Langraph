"""Translate the challenges-backend's flat webhook payloads into the nested
request dicts our stage schemas expect.

The backend sends project fields at the top level (``projectName``,
``clientContext``, ...). Our schemas nest them under ``project`` (a
:class:`ProjectContext`). This module is the single seam where that mapping
lives, so the backend never has to change.
"""

from __future__ import annotations

from typing import Any

from strategy_navigator.constants import Workflow
from strategy_navigator.errors import InvalidPayloadError

_PROJECT_FIELDS = (
    "projectId",
    "projectName",
    "projectDescription",
    "clientOrganization",
    "clientContext",
    "reportProfileForClient",
    "timeLines",
    "projectIntent",
    "stakeholders",
    "documents",
)


def _project_block(p: dict[str, Any]) -> dict[str, Any]:
    if "project" in p and isinstance(p["project"], dict):
        return p["project"]
    block = {k: p[k] for k in _PROJECT_FIELDS if k in p}
    if "projectId" not in block:
        raise InvalidPayloadError("payload is missing projectId / project block")
    block.setdefault("stakeholders", [])
    block.setdefault("documents", [])
    return block


def _session_id(p: dict[str, Any]) -> str:
    sid = (
        p.get("sessionId") or p.get("batchId") or p.get("triggerBatchId") or p.get("renderBatchId")
    )
    if not sid:
        raise InvalidPayloadError("payload is missing sessionId / batchId")
    return str(sid)


def _adapt_strategy_form_idea_generation(raw: Any) -> dict[str, Any]:
    """``raw`` here is a bare ARRAY, one item per customized template, all
    sharing one ``runId`` — see CustomizeTemplateService.processIdea. Do not
    run this through the generic single-element-array unwrap."""
    items = raw if isinstance(raw, list) else [raw]
    if not items:
        raise InvalidPayloadError("strategy_form_idea_generation payload is empty")
    run_id = items[0].get("runId")
    if not run_id:
        raise InvalidPayloadError("strategy_form_idea_generation payload is missing runId")
    templates: list[dict[str, Any]] = []
    for item in items:
        sol = item.get("solution") or {}
        if "projectId" not in sol:
            raise InvalidPayloadError(
                "strategy_form_idea_generation item is missing solution.projectId"
            )
        templates.append(sol)
    return {
        "sessionId": str(run_id),
        "projectId": templates[0]["projectId"],
        "templates": templates,
        "usermetadata": items[0].get("usermetadata") or {},
        "callbackUrl": items[0].get("callbackUrl"),
    }


def _adapt_strategic_foresight_report(raw: dict[str, Any]) -> dict[str, Any]:
    """Matches backend's ``ProjectStrategicForesightReportWebhookPayload`` —
    note the nested project block uses ``id``, not ``projectId``, unlike every
    other workflow's project block."""
    p = raw.get("project") or {}
    session_id = raw.get("sessionId")
    project_id = raw.get("projectId") or p.get("id")
    if not session_id or not project_id:
        raise InvalidPayloadError(
            "strategic_foresight_report payload is missing sessionId/projectId"
        )
    project = {
        "projectId": project_id,
        "projectName": p.get("projectName", ""),
        "projectDescription": p.get("projectDescription", ""),
        "clientOrganization": p.get("clientOrganization", ""),
        "clientContext": p.get("clientContext", ""),
        "reportProfileForClient": p.get("reportProfileForClient", ""),
        "timeLines": p.get("timeLines"),
        "projectIntent": p.get("projectIntent"),
        "stakeholders": p.get("stakeholders", []),
        "documents": p.get("documents", []),
    }
    return {
        "sessionId": str(session_id),
        "projectId": project_id,
        "project": project,
        "triggerBatchId": raw.get("triggerBatchId"),
        "ideationProcess": raw.get("ideationProcess", {}),
        "projectIdeas": raw.get("projectIdeas", []),
        "solutions": raw.get("solutions", []),
        "metrics": raw.get("metrics", {}),
        "callbackUrl": raw.get("callbackUrl"),
    }


def adapt(workflow: Workflow, raw: Any) -> dict[str, Any]:
    """``raw`` may be a bare object or n8n's single-element array wrapper."""
    if workflow == Workflow.STRATEGY_FORM_IDEA_GENERATION:
        return _adapt_strategy_form_idea_generation(raw)
    if isinstance(raw, list):
        if not raw:
            raise InvalidPayloadError("empty payload array")
        raw = raw[0]
    if not isinstance(raw, dict):
        raise InvalidPayloadError("payload must be an object")

    if workflow == Workflow.STRATEGIC_FORESIGHT_REPORT:
        return _adapt_strategic_foresight_report(raw)

    if workflow == Workflow.CAPSTONE_SUBSTRATE:
        # No top-level project block in this payload (see CapstoneSubstrateTriggerPayload) —
        # project context lives nested inside tenStepInput/ideasInput instead.
        ten_step_input = raw.get("tenStepInput") or {}
        session_id = raw.get("sessionId")
        project_id = raw.get("projectId") or ten_step_input.get("projectId")
        trigger_batch_id = raw.get("triggerBatchId")
        if not session_id or not project_id or not trigger_batch_id:
            raise InvalidPayloadError(
                "capstone_substrate payload is missing sessionId/projectId/triggerBatchId"
            )
        return {
            "sessionId": str(session_id),
            "projectId": project_id,
            "triggerBatchId": trigger_batch_id,
            "tenStepInput": ten_step_input,
            "ideasInput": raw.get("ideasInput") or {},
            "callbackUrl": raw.get("callbackUrl"),
        }

    project = _project_block(raw)
    session_id = _session_id(raw)
    common = {
        "sessionId": session_id,
        "project": project,
        "callbackUrl": raw.get("callbackUrl"),
        "documents": raw.get("documents", []),
    }

    if workflow == Workflow.DOMAIN_AGENT:
        return {
            **common,
            "documents": raw.get("documents", []),
            "minAgents": raw.get("minAgents", 3),
            "maxAgents": raw.get("maxAgents", 6),
        }

    if workflow == Workflow.IDEA_EXTRACTION:
        agent = raw.get("agent") or {}
        if not agent and raw.get("agentId"):
            agent = {"id": raw["agentId"], "name": raw.get("agentName", "Agent")}
        if not agent:
            raise InvalidPayloadError("idea_extraction payload has no agent")
        agent.setdefault("isDomainSpecific", raw.get("isDomainSpecific", False))
        return {
            **common,
            "agent": agent,
            "categories": raw.get("categories", []),
            "ideaCount": raw.get("ideaCount", 5),
            "researchQueries": raw.get("researchQueries", []),
        }

    if workflow == Workflow.RAPID_CONSOLIDATION:
        return {
            **common,
            "agents": raw.get("agents", []),
            "documentComments": raw.get("documentComments", []),
            "consolidationType": raw.get("consolidationType"),
        }

    if workflow == Workflow.FORESIGHT_CONSOLIDATION:
        return {**common, "solutions": raw.get("solutions", [])}

    if workflow == Workflow.VOTING:
        return {
            **common,
            "batchId": raw.get("batchId", session_id),
            "votingSessionId": raw.get("votingSessionId"),
            "agents": raw.get("agents", []),
            "ideas": raw.get("ideas", []),
            "childBatchSize": raw.get("childBatchSize", 10),
        }

    if workflow == Workflow.CUSTOM_ARCHETYPE:
        return {
            **common,
            "votingSessionId": raw.get("votingSessionId"),
            "spec": {
                "name": raw.get("name", "Custom report"),
                "purpose": raw.get("purpose", ""),
                "primaryReader": raw.get("primaryReader", ""),
                "pages": raw.get("pages", 10),
                "intendedUse": raw.get("intendedUse", ""),
                "sectionList": raw.get("sectionList", []),
                "template": raw.get("template"),
                "externalOptionsProminence": raw.get("externalOptionsProminence"),
                "divergenceDisplay": raw.get("divergenceDisplay"),
            },
        }

    if workflow == Workflow.REPORT_RENDER:
        return {
            **common,
            "renderBatchId": raw.get("renderBatchId", session_id),
            "votingSessionId": raw.get("votingSessionId"),
            "substrate": raw.get("substrate", {}),
            "selectedArchetypes": raw.get("selectedArchetypes", []),
        }

    if workflow == Workflow.FORM_FILLING_10STEP:
        agent = raw.get("agent") or {}
        if not agent:
            raise InvalidPayloadError("form_filling_10step payload has no agent")
        agent.setdefault("isDomainSpecific", raw.get("isDomainSpecific", False))
        return {
            **common,
            "agent": agent,
            "logId": raw.get("logId"),
            "completedSteps": raw.get("completedSteps", {}),
        }

    return {**common, "raw": raw}
