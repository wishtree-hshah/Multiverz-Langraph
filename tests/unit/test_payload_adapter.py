import pytest

from strategy_navigator.api.payload_adapter import adapt
from strategy_navigator.constants import Workflow
from strategy_navigator.errors import InvalidPayloadError
from strategy_navigator.schemas.domain import DomainAgentRequest
from strategy_navigator.schemas.ideas import IdeaExtractionRequest
from strategy_navigator.schemas.voting import VotingRequest


def test_adapt_lifts_flat_project_fields(sample_project):
    raw = {**sample_project, "sessionId": "s1"}
    out = adapt(Workflow.DOMAIN_AGENT, raw)
    req = DomainAgentRequest.model_validate(out)
    assert req.project.project_id == 42
    assert req.project.client_organization == "NorthGrid"
    assert req.session_id == "s1"


def test_adapt_unwraps_single_element_array(sample_project):
    raw = [{**sample_project, "sessionId": "s2", "agent": {"id": 7, "name": "Analyst"}}]
    out = adapt(Workflow.IDEA_EXTRACTION, raw)
    req = IdeaExtractionRequest.model_validate(out)
    assert req.agent.id == 7
    assert req.session_id == "s2"


def test_voting_uses_batch_id_as_session(sample_project):
    raw = {**sample_project, "batchId": "b-123", "agents": [], "ideas": []}
    out = adapt(Workflow.VOTING, raw)
    req = VotingRequest.model_validate(out)
    assert req.session_id == "b-123"
    assert req.batch_id == "b-123"


def test_missing_session_id_rejected(sample_project):
    with pytest.raises(InvalidPayloadError):
        adapt(Workflow.DOMAIN_AGENT, dict(sample_project))


def test_missing_project_id_rejected():
    with pytest.raises(InvalidPayloadError):
        adapt(Workflow.DOMAIN_AGENT, {"sessionId": "s", "projectName": "x"})
