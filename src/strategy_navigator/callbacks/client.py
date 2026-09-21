"""Deliver stage results back to challenges-backend.

The old n8n workflows POSTed a callback envelope (usually wrapped in a
single-element array) to a per-workflow ``callbackUrl``. We keep that contract so
the backend's existing callback controllers work unchanged.

Resolution order for the target URL:
1. ``callback_url`` carried on the run (backend passes it in the trigger payload)
2. ``SN_BACKEND_BASE_URL`` + the workflow's default callback path
"""

from __future__ import annotations

from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from strategy_navigator.config import settings
from strategy_navigator.constants import Workflow
from strategy_navigator.errors import BackendCallbackError
from strategy_navigator.logging import get_logger
from strategy_navigator.observability import span

log = get_logger(__name__)

# workflow -> default callback path on challenges-backend (see its n8n callback controllers)
_DEFAULT_PATH: dict[str, str] = {
    Workflow.DOMAIN_AGENT: "/n8n/callbacks/domain-specific-agents",
    Workflow.IDEA_EXTRACTION: "/n8n/callbacks/agent-ideas",
    Workflow.RAPID_CONSOLIDATION: "/n8n/callbacks/consolidation",
    Workflow.FORESIGHT_CONSOLIDATION: "/n8n/callbacks/foresight-consolidation",
    Workflow.VOTING: "/n8n/callbacks/voting-agent",
    Workflow.CAPSTONE_SUBSTRATE: "/n8n/callbacks/capstone-substrate",
    Workflow.REPORT_RENDER: "/n8n/callbacks/capstone-report-render",
    Workflow.CUSTOM_ARCHETYPE: "/n8n/callbacks/capstone-custom-archetype",
    # Not "/n8n/callbacks/..." like its siblings — this workflow has no separate
    # submission endpoint. Every step (1-9 mid-run, 10 as the run's normal final
    # delivery) posts to the same per-step checkpoint route the backend exposes
    # directly on customize-template (see stages/form_filling_10step.py).
    Workflow.FORM_FILLING_10STEP: "/customize-template/n8n-step-checkpoint",
    # customize-template.controller.ts: @Post('projects/strategic-foresight-report-callback')
    Workflow.STRATEGIC_FORESIGHT_REPORT: (
        "/customize-template/projects/strategic-foresight-report-callback"
    ),
    # customize-template.controller.ts: @Post('n8n-callback') — same shared endpoint
    # idea_extraction (Agent-ideas) posts to, but the body itself is the array
    # (wrapped under "results"), not a single-element-array-wrapped object.
    Workflow.STRATEGY_FORM_IDEA_GENERATION: "/customize-template/n8n-callback",
}

# workflows whose backend controller expects a bare object, not [obj]
_BARE_OBJECT = {
    Workflow.CAPSTONE_SUBSTRATE,
    Workflow.REPORT_RENDER,
    Workflow.CUSTOM_ARCHETYPE,
    Workflow.FORM_FILLING_10STEP,
    Workflow.STRATEGIC_FORESIGHT_REPORT,
    Workflow.STRATEGY_FORM_IDEA_GENERATION,
}


def _resolve_url(workflow: str, callback_url: str | None) -> str:
    if callback_url:
        return callback_url
    path = _DEFAULT_PATH.get(workflow)
    if not path:
        raise BackendCallbackError(f"No callback URL/path for workflow {workflow!r}")
    return f"{settings.backend_base_url.rstrip('/')}{path}"


@retry(
    retry=retry_if_exception_type((httpx.TransportError, BackendCallbackError)),
    wait=wait_exponential(multiplier=2, min=2, max=60),
    stop=stop_after_attempt(settings.backend_callback_max_retries),
    reraise=True,
)
async def post_callback(
    *, workflow: str, callback_url: str | None, session_id: str, body: dict[str, Any]
) -> None:
    url = _resolve_url(workflow, callback_url)
    payload: Any = body if Workflow(workflow) in _BARE_OBJECT else [body]
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if settings.backend_callback_token:
        headers["Authorization"] = f"Bearer {settings.backend_callback_token}"

    with span(f"callback.{workflow}", **{"sn.session_id": session_id}):
        async with httpx.AsyncClient(timeout=settings.backend_callback_timeout_s) as client:
            resp = await client.post(url, json=payload, headers=headers)
    if resp.status_code >= 400:
        raise BackendCallbackError(f"{workflow} callback -> {resp.status_code}: {resp.text[:300]}")
    log.info("callback.delivered", workflow=workflow, url=url, status=resp.status_code)
