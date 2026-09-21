"""Webhook endpoint accepts the backend's {workflow_name, payload} and enqueues."""

from __future__ import annotations

import contextlib

import pytest
from fastapi.testclient import TestClient


@contextlib.asynccontextmanager
async def _noop_lifespan(_app):
    yield


@pytest.fixture
def client(monkeypatch):
    enqueued: list[dict] = []

    async def _enqueue(**kw):
        enqueued.append(kw)

    monkeypatch.setattr("strategy_navigator.api.routes.webhooks.enqueue_run", _enqueue)
    monkeypatch.setattr("strategy_navigator.api.app._lifespan", _noop_lifespan)

    from strategy_navigator.api.app import create_app

    app = create_app()
    app.state.enqueued = enqueued
    with TestClient(app) as c:
        yield c


def test_trigger_accepts_backend_envelope(client, sample_project):
    body = {
        "workflow_name": "Domain-specific-agent-generation",
        "payload": {**sample_project, "sessionId": "sess-1"},
    }
    resp = client.post("/webhooks/trigger", json=body)
    assert resp.status_code == 202
    data = resp.json()
    assert data["workflow"] == "domain_agent"
    assert data["lane"] == "short"
    assert data["ported"] is True
    assert client.app.state.enqueued[0]["run_id"] == "domain_agent:sess-1"


def test_trigger_unknown_workflow_400(client):
    resp = client.post("/webhooks/trigger", json={"workflow_name": "nope", "payload": {}})
    assert resp.status_code == 400


def test_trigger_strategic_foresight_report_is_long_lane_stub(client, sample_project):
    body = {
        "workflow_name": "Report-Generation-Strategic-Foresight",
        "payload": {**sample_project, "sessionId": "r-1"},
    }
    resp = client.post("/webhooks/trigger", json=body)
    assert resp.status_code == 202
    assert resp.json()["lane"] == "long"
    assert resp.json()["ported"] is False


def test_trigger_form_filling_10step_is_ported(client, sample_project):
    body = {
        "workflow_name": "Strategy-form-submission",
        "payload": {
            **sample_project,
            "sessionId": "r-1",
            "agent": {
                "id": 1,
                "name": "Agent",
                "designation": "Economist",
                "description": "Analyse.",
            },
        },
    }
    resp = client.post("/webhooks/trigger", json=body)
    assert resp.status_code == 202
    data = resp.json()
    assert data["lane"] == "long"
    assert data["ported"] is True


def test_trigger_report_render_is_ported(client, sample_project):
    body = {
        "workflow_name": "Capstone-Report-Render",
        "payload": {**sample_project, "sessionId": "r-1", "substrate": {}},
    }
    resp = client.post("/webhooks/trigger", json=body)
    assert resp.status_code == 202
    data = resp.json()
    assert data["lane"] == "long"
    assert data["ported"] is True


def test_trigger_capstone_substrate_is_ported(client):
    body = {
        "workflow_name": "Capstone-Substrate-Generation",
        "payload": {
            "sessionId": "r-1",
            "projectId": 42,
            "triggerBatchId": "batch-1",
            "tenStepInput": {"solutions": []},
        },
    }
    resp = client.post("/webhooks/trigger", json=body)
    assert resp.status_code == 202
    data = resp.json()
    assert data["lane"] == "long"
    assert data["ported"] is True
