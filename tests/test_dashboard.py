"""Tests for the dashboard frontend serving."""

from __future__ import annotations

from fastapi.testclient import TestClient

from python.api.server import app

client = TestClient(app)


def test_root_returns_html():
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_html_contains_veritas():
    r = client.get("/")
    assert "Veritas" in r.text


def test_html_references_endpoints():
    body = client.get("/").text
    assert "/state" in body
    assert "/assumptions" in body
    assert "/trades" in body


def test_static_serves_index():
    r = client.get("/static/index.html")
    assert r.status_code == 200
    assert "Veritas" in r.text


def test_post_root_rejected():
    r = client.post("/")
    assert r.status_code == 405
