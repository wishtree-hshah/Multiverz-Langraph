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
    session_id: str
    trigger_batch_id: str | None = None
    project: ProjectContext
    voting_session_id: int | None = None
    callback_url: str | None = None
    voted_ideas: list[dict[str, Any]] = []
    context: dict[str, Any] = {}


class SubstrateCallback(CamelModel):
    session_id: str
    project_id: int
    trigger_batch_id: str | None = None
    status: str = "completed"
    execution_id: str | None = None
    substrate: dict[str, Any] = {}
    token_usage: list[dict] | None = None
    error_message: str | None = None


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


class ArchetypeSection(CamelModel):
    title: str
    purpose: str
    target_words: int = 400


class ArchetypeDefinition(CamelModel):
    name: str
    sections: list[ArchetypeSection]


class CustomArchetypeRequest(CamelModel):
    session_id: str
    project: ProjectContext
    voting_session_id: int | None = None
    spec: ArchetypeSpec
    callback_url: str | None = None


class CustomArchetypeCallback(CamelModel):
    session_id: str
    project_id: int
    archetype: ArchetypeDefinition
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
    session_id: str
    project_id: int
    render_batch_id: str | None = None
    status: str = "completed"
    report: dict[str, Any] = {}
    execution_id: str | None = None
    token_usage: list[dict] | None = None
    error_message: str | None = None
