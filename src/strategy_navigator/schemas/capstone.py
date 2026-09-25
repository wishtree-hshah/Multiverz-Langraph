"""capstone_substrate + report_render + custom_archetype stage I/O.

These mirror the flexible payloads in challenges-backend's substrate/render DTOs
(capstone-substrate-generation-webhook.dto.ts, capstone-render-trigger-payload.dto.ts,
capstone-custom-archetype-author-webhook.dto.ts). Substrate/report bodies are
large and semi-structured; keep them permissive until each node's schema is ported.
"""

from __future__ import annotations

from typing import Any

from strategy_navigator.schemas.common import CamelModel, ProjectContext


class SubstrateRequest(CamelModel):
    """Matches backend's real ``CapstoneSubstrateTriggerPayload`` exactly: no
    top-level ``project`` block (unlike every other workflow) — the project
    context lives nested inside ``tenStepInput.project`` /
    ``ideasInput.project``. ``tenStepInput``/``ideasInput`` are each a large,
    semi-structured per-contributor bundle (10-step form data, voted ideas);
    kept as permissive dicts and read field-by-field in stages/capstone_substrate.py,
    which documents the exact field paths traced from the n8n Code nodes.
    """

    session_id: str
    project_id: int
    trigger_batch_id: str
    ten_step_input: dict[str, Any]
    ideas_input: dict[str, Any] = {}
    callback_url: str | None = None


class SubstrateCallback(CamelModel):
    session_id: str
    project_id: int
    trigger_batch_id: str
    status: str = "completed"
    execution_id: str | None = None
    substrate: dict[str, Any] = {}
    token_usage: list[dict] | None = None
    error_message: str | None = None
    error_code: str | None = None
    jina_tokens: int | None = None


class ArchetypeSpec(CamelModel):
    name: str
    purpose: str = ""
    primary_reader: str = ""
    pages: int = 10
    intended_use: str = ""
    section_list: list[str] = []
    template: str | None = None
    external_options_prominence: str | None = None
    divergence_display: str | None = None


class CustomArchetypeRequest(CamelModel):
    session_id: str
    project: ProjectContext
    voting_session_id: int | None = None
    spec: ArchetypeSpec
    callback_url: str | None = None


class ProvenanceEntry(CamelModel):
    field: str
    source: str
    reason: str


class AssembledArchetype(CamelModel):
    """The LLM's normalised archetype, matching backend's ``AssembledArchetypeDto``."""

    name: str
    primary_reader: str
    template: str
    intended_use: str
    external_options_prominence: str
    divergence_display: str
    typical_pages: int
    section_list: list[str]
    body_is_count_driven: bool


class CustomArchetypeOutput(CamelModel):
    """Raw structured-output shape of the ``custom_archetype.system`` prompt."""

    archetype: AssembledArchetype
    provenance: list[ProvenanceEntry]
    needs_confirmation: bool = True


class CustomArchetypeCallback(CamelModel):
    session_id: str
    status: str = "assembled"
    archetype: AssembledArchetype | None = None
    provenance: list[ProvenanceEntry] | None = None
    execution_id: str | None = None
    token_usage: list[dict] | None = None
    error_message: str | None = None


class RenderRequest(CamelModel):
    session_id: str
    render_batch_id: str | None = None
    project: ProjectContext
    voting_session_id: int | None = None
    substrate: dict[str, Any]
    selected_archetypes: list[dict[str, Any]] = []
    callback_url: str | None = None


class RenderCallback(CamelModel):
    """Matches backend's ``RenderCallbackDto`` (render-callback.dto.ts) exactly:
    no ``sessionId`` field, ``reports`` is an array (one entry per triggered
    archetype — this stage always emits exactly one), ``status`` is one of
    completed/partial/failed.
    """

    render_batch_id: str
    project_id: int
    status: str = "completed"
    reports: list[dict[str, Any]] = []
    execution_id: str | None = None
    token_usage: list[dict] | None = None
    error_message: str | None = None
    jina_tokens: int | None = None
