"""Tests for the static HTML surfaces: demo playground + runner dashboard."""

from __future__ import annotations

from fastapi.testclient import TestClient

from python.api.server import app

client = TestClient(app)


# ── Verification demo page (primary) ──────────────────────────────

def test_root_serves_demo_page():
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_demo_mentions_verifier():
    body = client.get("/").text
    assert "Veritas" in body
    assert "verify/proposal" in body


def test_demo_has_three_gate_cards():
    body = client.get("/").text
    assert "GATE 1" in body and "GATE 2" in body and "GATE 3" in body


def test_demo_links_to_runner():
    assert "/runner" in client.get("/").text


# ── Runner dashboard (secondary) ─────────────────────────────────

def test_runner_serves_html():
    r = client.get("/runner")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_runner_references_endpoints():
    body = client.get("/runner").text
    assert "/state" in body
    assert "/assumptions" in body
    assert "/trades" in body


def test_runner_static_path_still_serves():
    r = client.get("/static/runner.html")
    assert r.status_code == 200
    assert "Veritas" in r.text


# ── Write methods rejected on both ───────────────────────────────

def test_post_root_rejected():
    assert client.post("/").status_code == 405


def test_post_runner_rejected():
    assert client.post("/runner").status_code == 405
