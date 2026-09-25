"""Shared schema primitives.

All models accept the challenges-backend's camelCase JSON *and* snake_case, and
serialise back to camelCase (``model_dump(by_alias=True)``) so callbacks match
what the old n8n workflows returned.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="ignore",
        str_strip_whitespace=True,
    )


class AgentType(StrEnum):
    FOUNDATIONAL = "foundational"
    CONTEXTUAL = "contextual"
    HUMAN = "human"


class Tier(StrEnum):
    LEAD = "Lead"
    CONTENDER = "Contender"
    WILDCARD = "Wildcard"


class Horizon(StrEnum):
    NEAR = "NEAR"
    MEDIUM = "MEDIUM"
    LONG = "LONG"


class DocumentRef(CamelModel):
    id: int | None = None
    key: str
    original_file_name: str | None = None


class ProjectContext(CamelModel):
    """The block every workflow payload carries (see all *-webhook.dto.ts)."""

    project_id: int
    project_name: str
    project_description: str = ""
    client_organization: str = ""
    client_context: str = ""
    report_profile_for_client: str = ""
    time_lines: str | None = None
    project_intent: str | None = None
    stakeholders: list[str] = []
    documents: list[str] = []


class AgentRef(CamelModel):
    id: int
    name: str
    designation: str | None = None
    description: str | None = None
    agent_type: AgentType = AgentType.FOUNDATIONAL
    is_domain_specific: bool = False
    stakeholder: str | None = None

    @property
    def source_key(self) -> str:
        """ "foundational:{id}" / "domain:{id}" — the parseable key n8n round-trips."""
        prefix = "domain" if self.is_domain_specific else "foundational"
        return f"{prefix}:{self.id}"


class Idea(CamelModel):
    title: str
    summary: str
    sources: list[str] = []
    categories: list[str] = []
    agent_id: int | None = None
    # Explicit alias, NOT the CamelModel default (which would auto-generate
    # "sourceAgents") — challenges-backend's foresight consolidation callback
    # handler (receiveForesightConsolidatedIdeasFromN8n) destructures this
    # literal snake_case key. Confirmed live: without the override every
    # foresight idea silently vanished (each hit the handler's own "missing
    # source_agents" skip branch) while the callback still returned 201 and
    # the run logged as succeeded.
    source_agents: list[str] = Field(default=[], alias="source_agents")
    tier: Tier | None = None
    horizon: Horizon | None = None
    is_domain_specific_agent: bool | None = None
