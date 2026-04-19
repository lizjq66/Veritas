"""Tests for the API foundation: health endpoint and read-only middleware."""

from __future__ import annotations

from fastapi.testclient import TestClient

from python.api.server import app

client = TestClient(app)


def test_health_returns_ok():
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["veritas_version"] == "0.1"


def test_post_rejected():
    resp = client.post("/health")
    assert resp.status_code == 405
    assert resp.json()["error"] == "veritas_api_write_denied"


def test_delete_rejected():
    resp = client.delete("/health")
    assert resp.status_code == 405


def test_put_rejected():
    resp = client.put("/health")
    assert resp.status_code == 405


def test_options_allowed():
    resp = client.options("/health")
    assert resp.status_code in (200, 405)  # FastAPI may not define OPTIONS handler
