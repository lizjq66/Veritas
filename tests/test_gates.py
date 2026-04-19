"""Tests for the three-gate verifier.

These are the tests that anchor the product definition. Each gate
receives structured input and returns a structured verdict; the test
suite exercises approve / resize / reject paths for each gate plus
the combined certificate.

The tests call the real Lean veritas-core binary via the bridge —
there is no mocking of the verifier. If these tests pass, the gates
are real.
"""

from __future__ import annotations

import pytest

from python.schemas import (
    AccountConstraints,
    Portfolio,
    PortfolioPosition,
    TradeProposal,
)
from python.verifier import Verifier


@pytest.fixture(scope="module")
def verifier() -> Verifier:
    return Verifier()


# ── Proposal fixtures ─────────────────────────────────────────────

def _long_on_positive_funding(notional: float = 1500.0) -> TradeProposal:
    return TradeProposal(
        direction="LONG", notional_usd=notional,
        funding_rate=0.0012, price=68000.0, timestamp=0,
    )


def _short_on_negative_funding(notional: float = 1500.0) -> TradeProposal:
    return TradeProposal(
        direction="SHORT", notional_usd=notional,
        funding_rate=-0.0008, price=68000.0, timestamp=0,
    )


def _long_on_neutral_funding(notional: float = 1500.0) -> TradeProposal:
    return TradeProposal(
        direction="LONG", notional_usd=notional,
        funding_rate=0.0001, price=68000.0, timestamp=0,
    )


def _good_constraints(reliability: float = 0.8,
                      sample_size: int = 20,
                      equity: float = 10000.0) -> AccountConstraints:
    return AccountConstraints(
        equity=equity, reliability=reliability, sample_size=sample_size,
        max_leverage=1.0, max_position_fraction=0.25, stop_loss_pct=5.0,
    )


# ── Gate 1: signal consistency ───────────────────────────────────

def test_gate1_approves_aligned_direction(verifier):
    verdict, assumptions = verifier.verify_signal(_long_on_positive_funding())
    assert verdict.tag == "approve"
    assert len(assumptions) >= 1
    assert assumptions[0]["name"] == "funding_rate_reverts_within_8h"


def test_gate1_rejects_wrong_direction(verifier):
    proposal = TradeProposal(
        direction="LONG", notional_usd=1500.0,
        funding_rate=-0.0008, price=68000.0, timestamp=0,
    )
    verdict, assumptions = verifier.verify_signal(proposal)
    assert verdict.tag == "reject"
    assert "direction_conflicts_with_signal" in verdict.reason_codes
    assert assumptions == ()


def test_gate1_rejects_when_policy_silent(verifier):
    verdict, _ = verifier.verify_signal(_long_on_neutral_funding())
    assert verdict.tag == "reject"
    assert "no_signal_under_policy" in verdict.reason_codes


# ── Gate 2: constraints ──────────────────────────────────────────

def test_gate2_approves_within_ceiling(verifier):
    proposal = _long_on_positive_funding(notional=1500.0)
    verdict = verifier.check_constraints(proposal, _good_constraints())
    assert verdict.tag == "approve"


def test_gate2_resizes_when_above_ceiling(verifier):
    # 90% reliability → Kelly ≈ 0.5*0.8 = 0.4; half-Kelly capped at 25% of 10k = 2500
    proposal = _long_on_positive_funding(notional=9000.0)
    verdict = verifier.check_constraints(proposal, _good_constraints(reliability=0.9, sample_size=30))
    assert verdict.tag == "resize"
    assert verdict.new_notional_usd is not None
    assert verdict.new_notional_usd == pytest.approx(2500.0, rel=1e-3)


def test_gate2_rejects_when_no_edge(verifier):
    proposal = _long_on_positive_funding(notional=1000.0)
    # reliability <= 0.5 post-exploration → zero ceiling → reject
    verdict = verifier.check_constraints(
        proposal, _good_constraints(reliability=0.5, sample_size=30)
    )
    assert verdict.tag == "reject"
    assert "no_edge_reliability_below_threshold" in verdict.reason_codes


def test_gate2_rejects_non_positive_leverage(verifier):
    proposal = _long_on_positive_funding(notional=1000.0)
    constraints = AccountConstraints(
        equity=10000.0, reliability=0.8, sample_size=20,
        max_leverage=0.0, max_position_fraction=0.25, stop_loss_pct=5.0,
    )
    verdict = verifier.check_constraints(proposal, constraints)
    assert verdict.tag == "reject"
    assert "leverage_cap_non_positive" in verdict.reason_codes


# ── Gate 3: portfolio ────────────────────────────────────────────

def test_gate3_approves_empty_portfolio(verifier):
    proposal = _long_on_positive_funding(notional=1000.0)
    verdict = verifier.check_portfolio(proposal, Portfolio(), equity=10000.0)
    assert verdict.tag == "approve"


def test_gate3_rejects_opposite_direction(verifier):
    proposal = _long_on_positive_funding(notional=1000.0)
    portfolio = Portfolio(
        positions=(PortfolioPosition(direction="SHORT", entry_price=67500.0, size=0.03),),
    )
    verdict = verifier.check_portfolio(proposal, portfolio, equity=10000.0)
    assert verdict.tag == "reject"
    assert "direction_conflicts_existing_position" in verdict.reason_codes


def test_gate3_resizes_when_breaches_gross_cap(verifier):
    # gross cap = equity * 0.50 = 5000; existing LONG at 68000 * 0.06 = 4080 notional;
    # proposing additional LONG notional of 5000 → total 9080 > cap → resize to headroom 920.
    proposal = _long_on_positive_funding(notional=5000.0)
    portfolio = Portfolio(
        positions=(PortfolioPosition(direction="LONG", entry_price=68000.0, size=0.06),),
        max_gross_exposure_fraction=0.50,
    )
    verdict = verifier.check_portfolio(proposal, portfolio, equity=10000.0)
    assert verdict.tag == "resize"
    assert verdict.new_notional_usd is not None
    assert verdict.new_notional_usd == pytest.approx(10000.0 * 0.50 - 68000.0 * 0.06, rel=1e-3)


def test_gate3_rejects_when_already_at_cap(verifier):
    proposal = _long_on_positive_funding(notional=1000.0)
    # Existing LONG with notional exactly at cap: entry * size = 68000 * 0.1 ≈ 6800
    # but gross cap = equity * 0.50 = 5000. existingGross 6800 > cap → headroom ≤ 0 → reject.
    portfolio = Portfolio(
        positions=(PortfolioPosition(direction="LONG", entry_price=68000.0, size=0.1),),
        max_gross_exposure_fraction=0.50,
    )
    verdict = verifier.check_portfolio(proposal, portfolio, equity=10000.0)
    assert verdict.tag == "reject"
    assert "portfolio_already_at_gross_exposure_cap" in verdict.reason_codes


# ── Combined certificate ─────────────────────────────────────────

def test_certificate_clean_approval(verifier):
    cert = verifier.verify(_long_on_positive_funding(), _good_constraints())
    assert cert.approves is True
    assert cert.gate1.tag == "approve"
    assert cert.gate2.tag == "approve"
    assert cert.gate3.tag == "approve"
    assert cert.final_notional_usd == pytest.approx(1500.0)
    assert len(cert.assumptions) >= 1


def test_certificate_gate1_rejection_short_circuits(verifier):
    cert = verifier.verify(_long_on_neutral_funding(), _good_constraints())
    assert cert.approves is False
    assert cert.gate1.tag == "reject"
    # Downstream gates receive the upstream-rejected marker
    assert cert.gate2.tag == "reject"
    assert "upstream_gate_rejected" in cert.gate2.reason_codes
    assert cert.gate3.tag == "reject"
    assert cert.final_notional_usd == 0.0


def test_certificate_resize_flows_to_gate3(verifier):
    # Gate 2 resizes to 2500; Gate 3 sees 2500 in an empty portfolio → approve.
    cert = verifier.verify(
        _long_on_positive_funding(notional=9000.0),
        _good_constraints(reliability=0.9, sample_size=30),
    )
    assert cert.approves is True
    assert cert.gate2.tag == "resize"
    assert cert.final_notional_usd == pytest.approx(2500.0, rel=1e-3)
