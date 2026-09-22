"""Deliver stage results back to challenges-backend.

The old n8n workflows POSTed a callback envelope (usually wrapped in a
single-element array) to a per-workflow ``callbackUrl``. We keep that contract so
the backend's existing callback controllers work unchanged.

Resolution order for the target URL:
1. ``callback_url`` carried on the run (backend passes it in the trigger payload)
2. ``SN_BACKEND_BASE_URL`` + the workflow's default callback path

Several callback routes (domain_agent, idea_extraction, rapid_consolidation,
foresight_consolidation) sit behind challenges-backend's ``SessionAuthGuard`` —
a logged-in-user session cookie, not the ``Authorization: Bearer`` token this
module also sends. When ``SN_BACKEND_LOGIN_EMAIL``/``SN_BACKEND_LOGIN_PASSWORD``
are set, we log in once (``POST {base_url}/auth/login``, same as the frontend)
and cache the ``sessionId`` cookie the backend's ``express-session`` issues,
re-fetching it on a 401 (expired/invalid) rather than on a fixed schedule.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from strategy_navigator.config import settings
from strategy_navigator.constants import Workflow
from strategy_navigator.errors import BackendCallbackError
from strategy_navigator.logging import get_logger
from strategy_navigator.observability import span

log = get_logger(__name__)

_session_cookie: str | None = None
_login_lock = asyncio.Lock()


async def _login(client: httpx.AsyncClient) -> str:
    url = f"{settings.backend_base_url.rstrip('/')}/auth/login"
    resp = await client.post(
        url,
        json={
            "email": settings.backend_login_email,
            "password": settings.backend_login_password,
            "type": "[Auth] Login",
        },
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    cookie = resp.cookies.get("sessionId")
    if resp.status_code >= 400 or not cookie:
        raise BackendCallbackError(
            f"backend login -> {resp.status_code}: {resp.text[:300]}"
        )
    log.info("callback.login_ok", url=url)
    return cookie


async def _session_cookie_header(client: httpx.AsyncClient) -> dict[str, str]:
    """Cached session cookie for routes behind SessionAuthGuard. No-op (empty
    headers) when login credentials aren't configured — most callback routes
    don't need this."""
    global _session_cookie
    if not settings.backend_login_email:
        return {}
    async with _login_lock:
        if _session_cookie is None:
            _session_cookie = await _login(client)
    return {"Cookie": f"sessionId={_session_cookie}"}


def _invalidate_session_cookie() -> None:
    global _session_cookie
    _session_cookie = None

# workflow -> default callback path on challenges-backend (see its n8n callback
# controllers). Verified directly against the backend source (@Controller +
# @Post decorators), not guessed — an earlier pass got 6 of these 11 wrong
# (real-world symptom: domain_agent's callback 404ing with "Cannot POST
# /n8n/callbacks/domain-specific-agents", which isn't a route that exists).
_DEFAULT_PATH: dict[str, str] = {
    # customize-template.controller.ts: @Post('n8n-domain-specific-agents-callback')
    Workflow.DOMAIN_AGENT: "/customize-template/n8n-domain-specific-agents-callback",
    # customize-template.controller.ts: @Post('n8n-agent-ideas-callback')
    Workflow.IDEA_EXTRACTION: "/customize-template/n8n-agent-ideas-callback",
    # customize-template.controller.ts: @Post('n8n-consolidation-callback')
    Workflow.RAPID_CONSOLIDATION: "/customize-template/n8n-consolidation-callback",
    # customize-template.controller.ts: @Post('n8n-foresight-consolidation-callback')
    Workflow.FORESIGHT_CONSOLIDATION: (
        "/customize-template/n8n-foresight-consolidation-callback"
    ),
    # voting-session.controller.ts (@Controller('customize-template/voting-sessions')):
    # @Post('n8n-agent-votes-callback') — NOT 'n8n-voting-agents-callback', which is
    # the same-shape-as-domain-agents callback for the *agent generation* step, not
    # the actual vote scoring this stage produces.
    Workflow.VOTING: "/customize-template/voting-sessions/n8n-agent-votes-callback",
    # n8n-callbacks.controller.ts (@Controller('n8n/callbacks')):
    Workflow.CAPSTONE_SUBSTRATE: "/n8n/callbacks/capstone-substrate",
    Workflow.REPORT_RENDER: "/n8n/callbacks/capstone-render",
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
            headers.update(await _session_cookie_header(client))
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 401 and settings.backend_login_email:
                # Cached cookie expired/invalid — log in again and retry once
                # inline (cheaper than waiting for tenacity's backoff window).
                _invalidate_session_cookie()
                headers.update(await _session_cookie_header(client))
                resp = await client.post(url, json=payload, headers=headers)
    if resp.status_code >= 400:
        raise BackendCallbackError(f"{workflow} callback -> {resp.status_code}: {resp.text[:300]}")
    log.info("callback.delivered", workflow=workflow, url=url, status=resp.status_code)
