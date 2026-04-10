"""Tests for all 6 API endpoints + read-only enforcement."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from python.api import db
from python.api.server import app
from python import journal


@pytest.fixture(autouse=True)
def _use_temp_db(tmp_path):
    """Each test gets its own fresh DB."""
    p = tmp_path / "test.db"
    # Create via journal (write mode) so tables exist
    journal._conn = None
    journal.init_db(p)
    journal.seed_assumptions()
    journal._conn = None
    # Point API db layer to this path (read-only)
    db.set_db_path(p)
    yield p


@pytest.fixture
def populated_db(_use_temp_db):
    """DB with 3 completed trades."""
    p = _use_temp_db
    journal._conn = None
    journal.init_db(p)
    journal.record_trade(
        entry_time="2024-01-01T00:00:00Z", direction="SHORT",
        entry_price=68000.0, size=0.001,
        assumption_name="funding_rate_reverts_within_8h",
        exit_time="2024-01-01T02:00:00Z", exit_price=67900.0,
        exit_reason="assumption_met", pnl=0.15,
    )
    journal.record_trade(
        entry_time="2024-01-01T04:00:00Z", direction="LONG",
        entry_price=69000.0, size=0.001,
        assumption_name="funding_rate_reverts_within_8h",
        exit_time="2024-01-01T06:00:00Z", exit_price=69200.0,
        exit_reason="assumption_met", pnl=0.29,
    )
    journal.record_trade(
        entry_time="2024-01-01T08:00:00Z", direction="SHORT",
        entry_price=68500.0, size=0.002,
        assumption_name="funding_rate_reverts_within_8h",
        exit_time="2024-01-01T10:00:00Z", exit_price=69000.0,
        exit_reason="stop_loss", pnl=-0.73,
    )
    journal.update_assumption_stats("funding_rate_reverts_within_8h", {"wins": 2, "total": 3})
    journal._conn = None
    return p


client = TestClient(app)


# ── /state ─────────────────────────────────────────────────────────

def test_state_empty():
    r = client.get("/state")
    assert r.status_code == 200
    d = r.json()
    assert d["phase"] == "exploration"
    assert d["trade_count"] == 0
    assert d["win_rate"] is None
    assert d["current_position"] is None


def test_state_populated(populated_db):
    r = client.get("/state")
    assert r.status_code == 200
    d = r.json()
    assert d["trade_count"] == 3
    assert d["phase"] == "exploration"
    assert d["win_rate"] == pytest.approx(2 / 3, abs=0.01)


# ── /assumptions ───────────────────────────────────────────────────

def test_assumptions_list():
    r = client.get("/assumptions")
    assert r.status_code == 200
    d = r.json()
    assert len(d["assumptions"]) == 1
    a = d["assumptions"][0]
    assert a["name"] == "funding_rate_reverts_within_8h"
    assert a["reliability"] == 0.5  # no trades yet


def test_assumptions_detail():
    r = client.get("/assumptions/funding_rate_reverts_within_8h")
    assert r.status_code == 200
    d = r.json()
    assert d["lean_theorem_path"] == "Veritas/Strategy/FundingReversion.lean"
    assert d["verification_status"] == "proven"
    assert "recent_outcomes" in d


def test_assumptions_detail_populated(populated_db):
    r = client.get("/assumptions/funding_rate_reverts_within_8h")
    d = r.json()
    assert d["wins"] == 2
    assert d["total"] == 3
    assert len(d["recent_outcomes"]) == 3


def test_assumptions_not_found():
    r = client.get("/assumptions/nonexistent")
    assert r.status_code == 404


# ── /trades ────────────────────────────────────────────────────────

def test_trades_empty():
    r = client.get("/trades")
    assert r.status_code == 200
    d = r.json()
    assert d["trades"] == []
    assert d["total"] == 0


def test_trades_populated(populated_db):
    r = client.get("/trades?limit=2&offset=0")
    assert r.status_code == 200
    d = r.json()
    assert len(d["trades"]) == 2
    assert d["total"] == 3


def test_trades_pagination(populated_db):
    r = client.get("/trades?limit=2&offset=2")
    d = r.json()
    assert len(d["trades"]) == 1


def test_trade_by_id(populated_db):
    r = client.get("/trades/1")
    assert r.status_code == 200
    d = r.json()
    assert d["direction"] == "SHORT"
    assert d["entry_price"] == 68000.0


def test_trade_not_found():
    r = client.get("/trades/999")
    assert r.status_code == 404


# ── /verify ────────────────────────────────────────────────────────

def test_verify_proven():
    r = client.get("/verify/positionSize_zero_at_no_edge")
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "proven"
    assert d["file"] == "Veritas/Finance/PositionSizing.lean"


def test_verify_sorry():
    r = client.get("/verify/positionSize_capped")
    assert r.status_code == 200
    assert r.json()["status"] == "sorry"


def test_verify_not_found():
    r = client.get("/verify/nonexistent_theorem")
    assert r.status_code == 404


# ── Read-only enforcement ──────────────────────────────────────────

def test_post_state_rejected():
    r = client.post("/state")
    assert r.status_code == 405
    assert r.json()["error"] == "veritas_api_is_read_only"


def test_put_trades_rejected():
    r = client.put("/trades/1")
    assert r.status_code == 405


def test_delete_assumptions_rejected():
    r = client.delete("/assumptions/funding_rate_reverts_within_8h")
    assert r.status_code == 405
