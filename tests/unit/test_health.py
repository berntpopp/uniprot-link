"""Unit tests for the /health endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient

from uniprot_link.app import app


def test_health_returns_required_keys() -> None:
    """/health must include status, version, and transport."""
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert body["transport"] == "streamable-http-stateless"
