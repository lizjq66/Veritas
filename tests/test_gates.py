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
    CorrelationEntry,
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


# ── Gate 1: signal consistency (single-policy legacy behavior) ────

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


# ── Gate 1: multi-policy behavior (v0.2 Slice 2) ─────────────────

def test_gate1_both_strategies_agree_attaches_both_assumptions(verifier):
    """Both funding-reversion and basis-reversion fire and both say LONG:
    funding +0.12%/hr (funding rev says LONG) and perp 67700 < spot 68000
    (basis rev says LONG). Approve with union of assumptions."""
    proposal = TradeProposal(
        direction="LONG", notional_usd=1500.0,
        funding_rate=0.0012, price=67700.0, timestamp=0,
        spot_price=68000.0,
    )
    verdict, assumptions = verifier.verify_signal(proposal)
    assert verdict.tag == "approve"
    names = {a["name"] for a in assumptions}
    assert "funding_rate_reverts_within_8h" in names
    assert "basis_reverts_within_24h" in names


def test_gate1_strategies_contradict_rejects(verifier):
    """Funding +0.12% says LONG perp; perp 68300 > spot 68000 says SHORT perp.
    Two firing strategies, opposite directions → Gate 1 rejects with
    `strategies_contradict`."""
    proposal = TradeProposal(
        direction="LONG", notional_usd=1500.0,
        funding_rate=0.0012, price=68300.0, timestamp=0,
        spot_price=68000.0,
    )
    verdict, assumptions = verifier.verify_signal(proposal)
    assert verdict.tag == "reject"
    assert "strategies_contradict" in verdict.reason_codes
    assert assumptions == ()


def test_gate1_only_basis_fires(verifier):
    """Funding rate 0 (below threshold) but perp 68300 > spot 68000 by 0.44%.
    Only basis-reversion fires; it says SHORT. Proposal SHORT is approved."""
    proposal = TradeProposal(
        direction="SHORT", notional_usd=1500.0,
        funding_rate=0.0, price=68300.0, timestamp=0,
        spot_price=68000.0,
    )
    verdict, assumptions = verifier.verify_signal(proposal)
    assert verdict.tag == "approve"
    names = {a["name"] for a in assumptions}
    assert "basis_reverts_within_24h" in names
    assert "funding_rate_reverts_within_8h" not in names


def test_gate1_liquidation_cascade_alone_fires(verifier):
    """Third strategy: liquidation cascade reversion. Net +$100M
    short-side liquidations → SHORT signal (revert the surge)."""
    proposal = TradeProposal(
        direction="SHORT", notional_usd=1500.0,
        funding_rate=0.0, price=68000.0, timestamp=0,
        liquidations24h=100_000_000.0,
    )
    verdict, assumptions = verifier.verify_signal(proposal)
    assert verdict.tag == "approve"
    names = {a["name"] for a in assumptions}
    assert "price_reverts_after_liquidation_cascade_within_4h" in names


def test_gate1_all_three_strategies_agree(verifier):
    """Funding +0.12% (LONG), perp cheap vs spot (LONG), net −$100M
    liquidations (longs stopped → LONG). All three agree → approve
    with THREE assumptions attached."""
    proposal = TradeProposal(
        direction="LONG", notional_usd=1500.0,
        funding_rate=0.0012, price=67700.0, timestamp=0,
        spot_price=68000.0, liquidations24h=-100_000_000.0,
    )
    verdict, assumptions = verifier.verify_signal(proposal)
    assert verdict.tag == "approve"
    names = {a["name"] for a in assumptions}
    assert names == {
        "funding_rate_reverts_within_8h",
        "basis_reverts_within_24h",
        "price_reverts_after_liquidation_cascade_within_4h",
    }


def test_gate1_three_way_partial_disagreement_rejects(verifier):
    """Funding +0.12% → LONG; basis (perp rich) → SHORT; cascade
    liquidations +$100M → SHORT. Two agree on SHORT, but one
    (funding) dissents → Gate 1 rejects as strategies_contradict."""
    proposal = TradeProposal(
        direction="SHORT", notional_usd=1500.0,
        funding_rate=0.0012, price=68300.0, timestamp=0,
        spot_price=68000.0, liquidations24h=100_000_000.0,
    )
    verdict, _ = verifier.verify_signal(proposal)
    assert verdict.tag == "reject"
    assert "strategies_contradict" in verdict.reason_codes


def test_gate1_cascade_below_threshold_does_not_fire(verifier):
    """|liquidations24h| = $10M is below the $50M threshold; cascade
    strategy stays silent."""
    proposal = TradeProposal(
        direction="LONG", notional_usd=1500.0,
        funding_rate=0.0012, price=68000.0, timestamp=0,
        liquidations24h=10_000_000.0,
    )
    verdict, assumptions = verifier.verify_signal(proposal)
    # funding still fires LONG, approves
    assert verdict.tag == "approve"
    names = {a["name"] for a in assumptions}
    assert "price_reverts_after_liquidation_cascade_within_4h" not in names
    assert "funding_rate_reverts_within_8h" in names


def test_gate1_both_fire_agree_but_proposal_wrong_direction(verifier):
    """Both strategies fire and agree on LONG, but caller proposed SHORT.
    Gate 1 rejects with direction_conflicts, NOT strategies_contradict."""
    proposal = TradeProposal(
        direction="SHORT", notional_usd=1500.0,
        funding_rate=0.0012, price=67700.0, timestamp=0,
        spot_price=68000.0,
    )
    verdict, _ = verifier.verify_signal(proposal)
    assert verdict.tag == "reject"
    assert "direction_conflicts_with_signal" in verdict.reason_codes
    assert "strategies_contradict" not in verdict.reason_codes


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
    assert "portfolio_already_at_correlation_weighted_cap" in verdict.reason_codes


# ── Gate 3: correlation-weighted exposure (v0.2 Slice 3) ─────────

def test_gate3_cross_asset_zero_correlation_approves(verifier):
    """BTC proposal vs ETH existing position with no correlation entry.
    Cross-asset unknown-correlation defaults to 0 → existing position
    contributes nothing to the BTC risk bucket → proposal approved."""
    proposal = TradeProposal(
        direction="LONG", notional_usd=2000.0,
        funding_rate=0.0012, price=68000.0, timestamp=0,
        asset="BTC",
    )
    portfolio = Portfolio(
        positions=(PortfolioPosition(
            direction="LONG", entry_price=2000.0, size=1.0, asset="ETH"),),
        max_gross_exposure_fraction=0.50,
        correlations=(),  # default: cross-asset = 0
    )
    verdict = verifier.check_portfolio(proposal, portfolio, equity=10000.0)
    assert verdict.tag == "approve"


def test_gate3_cross_asset_high_correlation_resizes(verifier):
    """BTC proposal vs ETH existing, with BTC-ETH correlation 0.9.
    Existing ETH = $2000 * 1 = $2000 notional; weighted by 0.9 → $1800
    contribution to BTC bucket. Proposal $4000 + $1800 = $5800 > $5000 cap.
    Headroom = cap($5000) − $1800 = $3200."""
    proposal = TradeProposal(
        direction="LONG", notional_usd=4000.0,
        funding_rate=0.0012, price=68000.0, timestamp=0,
        asset="BTC",
    )
    portfolio = Portfolio(
        positions=(PortfolioPosition(
            direction="LONG", entry_price=2000.0, size=1.0, asset="ETH"),),
        max_gross_exposure_fraction=0.50,
        correlations=(CorrelationEntry(asset_a="BTC", asset_b="ETH",
                                        coefficient=0.9),),
    )
    verdict = verifier.check_portfolio(proposal, portfolio, equity=10000.0)
    assert verdict.tag == "resize"
    assert verdict.new_notional_usd == pytest.approx(3200.0, rel=1e-3)


def test_gate3_cross_asset_symmetric_correlation_lookup(verifier):
    """Correlation table lookup should be symmetric: the entry
    BTC/ETH also matches an ETH proposal against a BTC position."""
    proposal = TradeProposal(
        direction="LONG", notional_usd=4000.0,
        funding_rate=0.0, price=2000.0, timestamp=0,
        asset="ETH",
    )
    portfolio = Portfolio(
        positions=(PortfolioPosition(
            direction="LONG", entry_price=68000.0, size=0.03, asset="BTC"),),
        max_gross_exposure_fraction=0.50,
        # Listed as BTC/ETH but must match ETH-proposal vs BTC-position.
        correlations=(CorrelationEntry(asset_a="BTC", asset_b="ETH",
                                        coefficient=0.9),),
    )
    # existing BTC weighted by 0.9: 68000*0.03*0.9 = $1836
    # proposal $4000 + $1836 = $5836 > $5000 cap → resize to $5000−$1836 = $3164
    verdict = verifier.check_portfolio(proposal, portfolio, equity=10000.0)
    assert verdict.tag == "resize"
    assert verdict.new_notional_usd == pytest.approx(3164.0, rel=1e-3)


def test_gate3_cross_asset_opposite_direction_is_not_conflict(verifier):
    """Contrast with same-asset: BTC-LONG proposal + ETH-SHORT
    existing position with zero correlation is NOT flagged as a
    direction conflict. The old (v0.1) logic would have rejected
    this because it treated all positions as same-asset."""
    proposal = TradeProposal(
        direction="LONG", notional_usd=1000.0,
        funding_rate=0.0012, price=68000.0, timestamp=0,
        asset="BTC",
    )
    portfolio = Portfolio(
        positions=(PortfolioPosition(
            direction="SHORT", entry_price=2000.0, size=0.5, asset="ETH"),),
        max_gross_exposure_fraction=0.50,
        correlations=(),
    )
    verdict = verifier.check_portfolio(proposal, portfolio, equity=10000.0)
    assert verdict.tag == "approve"


def test_gate3_same_asset_opposite_direction_still_rejected(verifier):
    """Regression: same-asset opposite-direction conflict detection
    must still work under the v0.2 asset-aware logic."""
    proposal = TradeProposal(
        direction="LONG", notional_usd=1000.0,
        funding_rate=0.0012, price=68000.0, timestamp=0,
        asset="BTC",
    )
    portfolio = Portfolio(
        positions=(PortfolioPosition(
            direction="SHORT", entry_price=68000.0, size=0.03, asset="BTC"),),
    )
    verdict = verifier.check_portfolio(proposal, portfolio, equity=10000.0)
    assert verdict.tag == "reject"
    assert "direction_conflicts_existing_position" in verdict.reason_codes


# ── Gate 3: linear VaR upper-bound check (v0.3 Slice 2) ──────────

def test_gate3_var_limit_zero_disables_check(verifier):
    """daily_var_limit=0 (default) preserves v0.2 single-check behavior.
    A very high volatility would blow any positive limit, yet here the
    check is skipped entirely."""
    proposal = TradeProposal(
        direction="LONG", notional_usd=1000.0,
        funding_rate=0.0012, price=68000.0, timestamp=0,
        volatility=0.5,
    )
    verdict = verifier.check_portfolio(
        proposal, Portfolio(), equity=10000.0, daily_var_limit=0.0,
    )
    assert verdict.tag == "approve"


def test_gate3_var_limit_approves_under(verifier):
    """Proposal-only bound = $1000 * 0.03 = $30. Limit $100 → approve."""
    proposal = TradeProposal(
        direction="LONG", notional_usd=1000.0,
        funding_rate=0.0012, price=68000.0, timestamp=0,
        volatility=0.03,
    )
    verdict = verifier.check_portfolio(
        proposal, Portfolio(), equity=10000.0, daily_var_limit=100.0,
    )
    assert verdict.tag == "approve"


def test_gate3_var_limit_rejects_over(verifier):
    """Proposal-only bound = $1000 * 0.03 = $30. Limit $20 → reject
    with reason ``portfolio_var_limit_exceeded``."""
    proposal = TradeProposal(
        direction="LONG", notional_usd=1000.0,
        funding_rate=0.0012, price=68000.0, timestamp=0,
        volatility=0.03,
    )
    verdict = verifier.check_portfolio(
        proposal, Portfolio(), equity=10000.0, daily_var_limit=20.0,
    )
    assert verdict.tag == "reject"
    assert "portfolio_var_limit_exceeded" in verdict.reason_codes


def test_gate3_var_bound_includes_same_asset_position(verifier):
    """Same-asset correlation is 1.0, so an existing LONG contributes
    its full |notional| * volatility to the bound.

    existing: $50000 * 0.02 = $1000 notional at vol 0.05 → $50
    proposal: $500 at vol 0.04 → $20
    total bound = $70. Limit $60 → reject."""
    proposal = TradeProposal(
        direction="LONG", notional_usd=500.0,
        funding_rate=0.0012, price=50000.0, timestamp=0,
        volatility=0.04,
    )
    portfolio = Portfolio(
        positions=(PortfolioPosition(
            direction="LONG", entry_price=50000.0, size=0.02,
            volatility=0.05),),
    )
    verdict = verifier.check_portfolio(
        proposal, portfolio, equity=10000.0, daily_var_limit=60.0,
    )
    assert verdict.tag == "reject"
    assert "portfolio_var_limit_exceeded" in verdict.reason_codes


def test_gate3_var_bound_weights_cross_asset_by_correlation(verifier):
    """Cross-asset existing contributes |corr| * |notional| * vol.

    existing ETH: $2000 * 1.0 = $2000 notional at vol 0.05, weighted by
      |corr(BTC,ETH)|=0.5 → $50
    proposal BTC: $1000 at vol 0.03 → $30
    total bound = $80. Limit $70 → reject; limit $100 → approve."""
    proposal = TradeProposal(
        direction="LONG", notional_usd=1000.0,
        funding_rate=0.0012, price=68000.0, timestamp=0,
        asset="BTC", volatility=0.03,
    )
    portfolio = Portfolio(
        positions=(PortfolioPosition(
            direction="LONG", entry_price=2000.0, size=1.0,
            asset="ETH", volatility=0.05),),
        correlations=(CorrelationEntry(
            asset_a="BTC", asset_b="ETH", coefficient=0.5),),
    )
    reject = verifier.check_portfolio(
        proposal, portfolio, equity=10000.0, daily_var_limit=70.0,
    )
    assert reject.tag == "reject"
    assert "portfolio_var_limit_exceeded" in reject.reason_codes
    approve = verifier.check_portfolio(
        proposal, portfolio, equity=10000.0, daily_var_limit=100.0,
    )
    assert approve.tag == "approve"


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
