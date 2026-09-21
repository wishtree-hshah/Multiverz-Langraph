"""domain_agent stage I/O."""

from __future__ import annotations

from pydantic import Field

from strategy_navigator.schemas.common import CamelModel, DocumentRef, ProjectContext


class DomainAgentRequest(CamelModel):
    session_id: str
    project: ProjectContext
    documents: list[DocumentRef] = []
    min_agents: int = 3
    max_agents: int = 6
    callback_url: str | None = None


class DomainAgentPersona(CamelModel):
    name: str
    designation: str
    description: str
    stakeholder: str | None = None


class DomainAgentOutput(CamelModel):
    personas: list[DomainAgentPersona] = Field(min_length=1)


class DomainAgentCallback(CamelModel):
    session_id: str
    project_id: int
    agents: list[DomainAgentPersona]
    execution_id: str | None = None
    token_usage: list[dict] | None = None
    error_message: str | None = None
