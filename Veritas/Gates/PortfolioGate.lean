/-
  Veritas.Gates.PortfolioGate — Gate 3: portfolio interference.

  Given the caller's existing positions and a new proposed trade,
  decide whether adding the trade would violate portfolio-level
  constraints.

  v0.2 upgrade: exposure is now measured with a correlation weighting
  across assets. An existing BTC-LONG position and an incoming
  ETH-LONG proposal do not contribute $1 : $1 to the cap check; they
  contribute in proportion to the BTC--ETH correlation supplied in
  the portfolio. Same-asset positions default to correlation 1.0
  (preserving v0.1 behavior); unknown cross-asset pairs default to 0.

  Three reject paths and one resize path:

    - direction_conflicts_existing_position  — a position on the
      same asset carries the opposite direction
    - gross_exposure_cap_non_positive        — cap is ≤ 0
    - portfolio_already_at_correlation_weighted_cap
        — the correlation-adjusted exposure already exceeds the cap
    - Resize headroom                        — the proposal would
      breach the cap; resize down to whatever headroom remains
-/
import Veritas.Gates.Types

namespace Veritas.Gates

open Veritas

/-- Absolute |correlation| between two assets under a portfolio's
    correlation table. Same-asset pairs resolve to 1.0 even with no
    explicit entry (so v0.1 single-asset callers are unaffected).
    Unknown cross-asset pairs resolve to 0.0 (new positions on
    unknown assets are treated as orthogonal for v0.2). -/
def correlationBetween
    (table : List CorrelationEntry) (a b : String) : Float :=
  if a == b then 1.0
  else
    match table.find?
      (fun e => (e.assetA == a && e.assetB == b)
              ∨ (e.assetA == b && e.assetB == a)) with
    | some e => Float.abs e.coefficient
    | none   => 0.0

/-- Sum of each existing position's absolute notional weighted by
    |correlation| with the proposed asset. This is the v0.2 measure
    of "how much of the portfolio overlaps with the new proposal's
    risk factor". -/
def correlationAdjustedExposure
    (port : Portfolio) (p : TradeProposal) : Float :=
  port.positions.foldl
    (fun acc pos =>
      acc +
      Float.abs (pos.entryPrice * pos.size) *
        correlationBetween port.correlations pos.asset p.asset)
    0.0

/-- Does any existing position on the same asset carry the opposite
    direction? Cross-asset opposite directions are NOT a conflict —
    they may even be a hedge. -/
def hasDirectionConflict
    (positions : List Position) (p : TradeProposal) : Bool :=
  positions.any
    (fun pos => pos.asset == p.asset && pos.direction != p.direction)

/-- Gate 3: check portfolio interference under correlation weighting. -/
def checkPortfolio
    (p : TradeProposal) (port : Portfolio) (equity : Float) : Verdict :=
  if hasDirectionConflict port.positions p then
    .Reject ["direction_conflicts_existing_position"]
  else
    let adjusted := correlationAdjustedExposure port p
    let cap := equity * port.maxGrossExposureFraction
    let proposed := Float.abs p.notionalUsd
    let total := adjusted + proposed
    if cap <= 0.0 then
      .Reject ["gross_exposure_cap_non_positive"]
    else if total <= cap then
      .Approve
    else
      let headroom := cap - adjusted
      if headroom <= 0.0 then
        .Reject ["portfolio_already_at_correlation_weighted_cap"]
      else
        .Resize headroom

-- ── Soundness contract ────────────────────────────────────────────

/-- Gate 3 soundness (approve path): if `checkPortfolio` approves the
    proposal, the proposal's absolute notional added to the existing
    correlation-adjusted exposure stays within the portfolio's cap.

    In v0.2 the "exposure" measure is `correlationAdjustedExposure`
    rather than raw gross notional: same-asset positions count fully,
    cross-asset positions count proportional to their correlation
    coefficient with the proposal's asset, unknown cross-asset pairs
    count as zero. Both endpoints (same-asset 1.0, different-asset 0.0
    default) match what v0.1 checked for its single-asset case. -/
theorem checkPortfolio_approve_respects_cap
    (p : TradeProposal) (port : Portfolio) (equity : Float)
    (h : checkPortfolio p port equity = .Approve) :
    correlationAdjustedExposure port p + Float.abs p.notionalUsd
      ≤ equity * port.maxGrossExposureFraction := by
  -- Rewrite `h` past the internal let-bindings so `split at` can
  -- descend into the if-chain.
  have h' :
      (if hasDirectionConflict port.positions p then
        Verdict.Reject ["direction_conflicts_existing_position"]
       else if equity * port.maxGrossExposureFraction ≤ 0.0 then
        Verdict.Reject ["gross_exposure_cap_non_positive"]
       else if correlationAdjustedExposure port p + Float.abs p.notionalUsd
              ≤ equity * port.maxGrossExposureFraction then
        Verdict.Approve
       else if equity * port.maxGrossExposureFraction
               - correlationAdjustedExposure port p ≤ 0.0 then
        Verdict.Reject ["portfolio_already_at_correlation_weighted_cap"]
       else
        Verdict.Resize (equity * port.maxGrossExposureFraction
                         - correlationAdjustedExposure port p))
        = .Approve := h
  split at h'
  · cases h'
  · split at h'
    · cases h'
    · split at h'
      · rename_i hle; exact hle
      · split at h'
        · cases h'
        · cases h'

end Veritas.Gates
