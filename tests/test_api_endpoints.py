"""Tests for all 6 API endpoints + read-only enforcement."""

from __future__ import annotations

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
    # v0.2 seeds both funding and basis reversion assumptions.
    names = {a["name"] for a in d["assumptions"]}
    assert "funding_rate_reverts_within_8h" in names
    assert "basis_reverts_within_24h" in names
    # both start at default 0.5 reliability (no trades yet)
    for a in d["assumptions"]:
        assert a["reliability"] == 0.5


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


# ── /verify/theorem ────────────────────────────────────────────────

def test_verify_theorem_proven():
    r = client.get("/verify/theorem/positionSize_zero_at_no_edge")
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "proven"
    assert d["file"] == "Veritas/Finance/PositionSizing.lean"


def test_verify_theorem_not_found():
    r = client.get("/verify/theorem/nonexistent_theorem")
    assert r.status_code == 404


def test_verify_theorem_legacy_path():
    r = client.get("/verify/positionSize_zero_at_no_edge")
    assert r.status_code == 200
    assert r.json()["status"] == "proven"


# ── /verify/proposal (primary product surface) ─────────────────────

def _proposal_body(**overrides) -> dict:
    body = {
        "proposal": {
            "direction": "LONG",
            "notional_usd": 1500.0,
            "funding_rate": 0.0012,
            "price": 68000.0,
            "timestamp": 0,
            "open_interest": 0.0,
        },
        "constraints": {
            "equity": 10000.0,
            "reliability": 0.8,
            "sample_size": 20,
            "max_leverage": 1.0,
            "max_position_fraction": 0.25,
            "stop_loss_pct": 5.0,
        },
        "portfolio": None,
    }
    for k, v in overrides.items():
        body[k] = v
    return body


def test_verify_proposal_clean_approval():
    r = client.post("/verify/proposal", json=_proposal_body())
    assert r.status_code == 200
    d = r.json()
    assert d["approves"] is True
    assert d["gate1"]["verdict"] == "approve"
    assert d["gate2"]["verdict"] == "approve"
    assert d["gate3"]["verdict"] == "approve"


def test_verify_proposal_direction_conflict():
    body = _proposal_body()
    body["proposal"]["funding_rate"] = -0.0008
    r = client.post("/verify/proposal", json=body)
    assert r.status_code == 200
    d = r.json()
    assert d["approves"] is False
    assert "direction_conflicts_with_signal" in d["gate1"]["reason_codes"]


def test_verify_signal_only():
    r = client.post("/verify/signal", json=_proposal_body())
    assert r.status_code == 200
    assert r.json()["gate"] == 1
    assert r.json()["result"]["verdict"] == "approve"


def test_verify_constraints_only():
    r = client.post("/verify/constraints", json=_proposal_body())
    assert r.status_code == 200
    assert r.json()["gate"] == 2
    assert r.json()["result"]["verdict"] == "approve"


def test_verify_portfolio_only():
    r = client.post("/verify/portfolio", json=_proposal_body())
    assert r.status_code == 200
    assert r.json()["gate"] == 3
    assert r.json()["result"]["verdict"] == "approve"


# ── Read-only enforcement (POST allowed only on /verify/*) ─────────

def test_post_state_rejected():
    r = client.post("/state")
    assert r.status_code == 405
    assert r.json()["error"] == "veritas_api_write_denied"


def test_put_trades_rejected():
    r = client.put("/trades/1")
    assert r.status_code == 405


def test_delete_assumptions_rejected():
    r = client.delete("/assumptions/funding_rate_reverts_within_8h")
    assert r.status_code == 405


def test_post_trades_rejected():
    r = client.post("/trades")
    assert r.status_code == 405
