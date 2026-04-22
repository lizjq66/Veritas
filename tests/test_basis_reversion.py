"""Tests for the v0.2 BasisReversion strategy.

Slice 1 scope: BasisReversion exists as a standalone Lean module
callable via the CLI and the Python bridge. It is NOT yet wired into
Gate 1 — Slice 2 will make Gate 1 dispatch to a policy registry that
includes this strategy.

These tests exercise the strategy in isolation so subsequent slices
can reshape the Gate 1 surface without regressing the underlying
policy behavior.
"""

from __future__ import annotations

import pytest

from python.bridge import VeritasCore


@pytest.fixture(scope="module")
def core() -> VeritasCore:
    return VeritasCore()


# ── decide_basis — direction logic ───────────────────────────────

def test_decide_basis_perp_rich_returns_short(core):
    """Perp trades 0.44% above spot (> 0.20% threshold) → SHORT."""
    sig = core.decide_basis(perp_price=68_300.0, spot_price=68_000.0)
    assert sig is not None
    assert sig["direction"] == "SHORT"
    assert sig["strategy"] == "basis_reversion"
    assert sig["perp_price"] == pytest.approx(68_300.0)
    assert sig["spot_price"] == pytest.approx(68_000.0)


def test_decide_basis_perp_cheap_returns_long(core):
    """Perp trades 0.44% below spot → LONG."""
    sig = core.decide_basis(perp_price=67_700.0, spot_price=68_000.0)
    assert sig is not None
    assert sig["direction"] == "LONG"


def test_decide_basis_in_band_returns_none(core):
    """Perp 0.05% above spot — well below the 0.20% threshold."""
    sig = core.decide_basis(perp_price=68_034.0, spot_price=68_000.0)
    assert sig is None


def test_decide_basis_missing_spot_returns_none(core):
    """Spot price of 0 means 'spot unknown'; strategy refuses to fire."""
    sig = core.decide_basis(perp_price=68_000.0, spot_price=0.0)
    assert sig is None


def test_decide_basis_negative_spot_returns_none(core):
    """Defensive: negative spot is nonsensical; strategy refuses."""
    sig = core.decide_basis(perp_price=68_000.0, spot_price=-1.0)
    assert sig is None


# ── boundary: exactly-at-threshold ───────────────────────────────

def test_decide_basis_exactly_at_threshold_does_not_fire(core):
    """|basis| == 0.20% is NOT > threshold; should return None."""
    # 68_000 * 1.002 = 68_136 → basis fraction = 0.002 exactly
    sig = core.decide_basis(perp_price=68_136.0, spot_price=68_000.0)
    assert sig is None


def test_decide_basis_just_over_threshold_fires(core):
    """|basis| just over 0.20% → signal fires."""
    # 68_000 * 1.0021 = 68_142.80 → basis fraction = 0.0021 > 0.002
    sig = core.decide_basis(perp_price=68_142.80, spot_price=68_000.0)
    assert sig is not None
    assert sig["direction"] == "SHORT"


# ── extract_basis — assumption attachment ────────────────────────

def test_extract_basis_returns_one_assumption(core):
    assumptions = core.extract_basis(
        {"direction": "SHORT", "price": 68_300.0})
    assert len(assumptions) == 1
    assert assumptions[0]["name"] == "basis_reverts_within_24h"
    assert "24 hours" in assumptions[0]["description"]


def test_extract_basis_same_assumption_regardless_of_direction(core):
    """Direction shouldn't change which assumption the policy attaches."""
    short_a = core.extract_basis({"direction": "SHORT", "price": 68_300.0})
    long_a  = core.extract_basis({"direction": "LONG",  "price": 67_700.0})
    assert [a["name"] for a in short_a] == [a["name"] for a in long_a]


# ── independence from FundingReversion ──────────────────────────

def test_decide_basis_ignores_funding_rate(core):
    """BasisReversion's direction comes from perp/spot only, not funding.

    Contrast with FundingReversion: this same context (funding +0.12%/hr)
    would signal LONG via FundingReversion. BasisReversion sees perp rich
    vs spot and signals SHORT. The two strategies disagreeing on this
    exact market context is what makes Gate 1's future consistency
    check non-trivial.
    """
    sig = core.decide_basis(perp_price=68_300.0, spot_price=68_000.0)
    assert sig["direction"] == "SHORT"
    # confirm FundingReversion would disagree on the same context
    from python.bridge import VeritasCore
    snap = {"funding_rate": 0.0012, "btc_price": 68_300.0, "timestamp": 0}
    funding_sig = core.decide(snap)
    assert funding_sig is not None
    assert funding_sig["direction"] == "LONG"
    # key property: two strategies, opposite directions, same snapshot
    assert funding_sig["direction"] != sig["direction"]
