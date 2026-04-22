"""Tests for the Veritas MCP server."""

from __future__ import annotations

import pytest

from python.api import db
from python.mcp.server import (
    TOOLS,
    _handle_get_state,
    _handle_list_assumptions,
    _handle_get_assumption,
    _handle_get_recent_trades,
    _handle_verify_theorem,
    _handle_verify_proposal,
    _handle_list_theorems,
    _handle_would_take_signal,
)
from python import journal


@pytest.fixture(autouse=True)
def _setup_db(tmp_path):
    """Each test gets a fresh DB."""
    p = tmp_path / "test.db"
    journal._conn = None
    journal.init_db(p)
    journal.seed_assumptions()
    journal._conn = None
    db.set_db_path(p)
    yield p


@pytest.fixture
def populated_db(_setup_db):
    p = _setup_db
    journal._conn = None
    journal.init_db(p)
    for i in range(3):
        reason = "assumption_met" if i < 2 else "stop_loss"
        journal.record_trade(
            entry_time=f"2024-01-01T{i*2:02d}:00:00Z",
            direction="LONG" if i % 2 == 0 else "SHORT",
            entry_price=68000.0 + i * 500,
            size=0.001,
            assumption_name="funding_rate_reverts_within_8h",
            exit_time=f"2024-01-01T{i*2+1:02d}:00:00Z",
            exit_price=68100.0 + i * 500,
            exit_reason=reason,
            pnl=0.15 if reason == "assumption_met" else -0.73,
        )
    journal.update_assumption_stats(
        "funding_rate_reverts_within_8h", {"wins": 2, "total": 3}
    )
    journal._conn = None
    return p


# ── Tool registration ────────────────────────────────────────────

def test_all_tools_registered():
    names = {t.name for t in TOOLS}
    expected = {
        "verify_proposal",       # primary surface
        "list_assumptions",
        "get_assumption",
        "verify_theorem",
        "list_theorems",
        "get_runner_state",
        "get_recent_trades",
    }
    assert names == expected


def test_primary_tool_is_verify_proposal():
    """The first registered tool is the primary product surface."""
    assert TOOLS[0].name == "verify_proposal"


def test_verify_proposal_clean_approval():
    d = _handle_verify_proposal({
        "direction": "LONG",
        "notional_usd": 1500.0,
        "funding_rate": 0.0012,
        "price": 68000.0,
        "equity": 10000.0,
        "reliability": 0.8,
        "sample_size": 20,
    })
    assert d["approves"] is True
    assert d["gate1"]["verdict"] == "approve"
    assert d["gate2"]["verdict"] == "approve"
    assert d["gate3"]["verdict"] == "approve"


def test_verify_proposal_direction_conflict():
    d = _handle_verify_proposal({
        "direction": "LONG",
        "notional_usd": 1500.0,
        "funding_rate": -0.0008,   # policy would signal SHORT
        "price": 68000.0,
        "equity": 10000.0,
        "reliability": 0.8,
        "sample_size": 20,
    })
    assert d["approves"] is False
    assert "direction_conflicts_with_signal" in d["gate1"]["reason_codes"]


def test_list_theorems_returns_all():
    d = _handle_list_theorems()
    names = {t["name"] for t in d["theorems"]}
    assert "positionSize_capped" in names
    assert "exitReason_exhaustive" in names


def test_tools_have_descriptions():
    for t in TOOLS:
        assert t.description, f"Tool '{t.name}' has no description"
        assert len(t.description) > 10


def test_tools_have_input_schemas():
    for t in TOOLS:
        assert t.inputSchema is not None
        assert t.inputSchema["type"] == "object"


# ── get_state ────────────────────────────────────────────────────

def test_get_state_empty():
    d = _handle_get_state()
    assert d["phase"] == "exploration"
    assert d["trade_count"] == 0
    assert d["win_rate"] is None


def test_get_state_populated(populated_db):
    d = _handle_get_state()
    assert d["trade_count"] == 3
    assert d["win_rate"] == pytest.approx(2 / 3, abs=0.01)


# ── list_assumptions ─────────────────────────────────────────────

def test_list_assumptions():
    d = _handle_list_assumptions()
    names = {a["name"] for a in d["assumptions"]}
    assert "funding_rate_reverts_within_8h" in names
    assert "basis_reverts_within_24h" in names


# ── get_assumption ───────────────────────────────────────────────

def test_get_assumption_exists():
    d = _handle_get_assumption("funding_rate_reverts_within_8h")
    assert "reliability" in d
    assert d["verification_status"] == "proven"


def test_get_assumption_populated(populated_db):
    d = _handle_get_assumption("funding_rate_reverts_within_8h")
    assert d["wins"] == 2
    assert d["total"] == 3
    assert len(d["recent_outcomes"]) == 3


def test_get_assumption_not_found():
    d = _handle_get_assumption("nonexistent")
    assert d["error"] == "not_found"


# ── get_recent_trades ────────────────────────────────────────────

def test_get_recent_trades_empty():
    d = _handle_get_recent_trades()
    assert d["trades"] == []
    assert d["total"] == 0


def test_get_recent_trades_populated(populated_db):
    d = _handle_get_recent_trades(limit=2)
    assert len(d["trades"]) == 2
    assert d["total"] == 3


# ── verify_theorem ───────────────────────────────────────────────

def test_verify_proven():
    d = _handle_verify_theorem("exitReason_exhaustive")
    assert d["status"] == "proven"


def test_verify_proven_position_capped():
    d = _handle_verify_theorem("positionSize_capped")
    assert d["status"] == "proven"


def test_verify_not_found():
    d = _handle_verify_theorem("nonexistent")
    assert d["error"] == "not_found"


# ── would_take_signal ────────────────────────────────────────────

def test_would_take_signal_no_data():
    """With default 0.5 reliability and 0 trades → exploration phase."""
    d = _handle_would_take_signal("LONG")
    assert d["would_execute"] is True
    assert d["position_size_usd"] == 100.0  # 1% of 10k
    assert "Exploration" in d["reason"]


def test_would_take_signal_high_reliability(populated_db):
    """With 2/3 reliability → would execute with Kelly sizing."""
    d = _handle_would_take_signal("SHORT", "BTC")
    assert d["would_execute"] is True
    assert d["assumption_reliability"] == pytest.approx(2 / 3, abs=0.01)
    assert d["relevant_assumption"] == "funding_rate_reverts_within_8h"


def test_would_take_signal_low_reliability(populated_db):
    """Force reliability ≤ 0.5 → no edge, would not execute."""
    journal._conn = None
    journal.init_db(populated_db)
    journal.update_assumption_stats(
        "funding_rate_reverts_within_8h", {"wins": 5, "total": 10}
    )
    journal._conn = None
    d = _handle_would_take_signal("LONG")
    assert d["would_execute"] is False
    assert "No edge" in d["reason"]
