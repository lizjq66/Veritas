/-
  Veritas.Gates.PortfolioGate — Gate 3: portfolio interference.

  Given existing positions and a new proposed trade, decide whether
  adding the trade would violate portfolio-level constraints.

  v0.2 upgrade: exposure is measured with correlation weighting.
  Same-asset positions default to correlation 1; unknown cross-asset
  pairs default to 0; explicit entries override both.

  v0.2 Slice 5: the whole arithmetic stack runs on exact `Rat`.

  Reject paths:
    - direction_conflicts_existing_position
    - gross_exposure_cap_non_positive
    - portfolio_already_at_correlation_weighted_cap
  Resize path:
    - correlation-adjusted exposure would breach the cap; resize down
-/
import Veritas.Gates.Types
import Mathlib.Algebra.Order.Ring.Abs
import Mathlib.Algebra.Order.Ring.Rat

namespace Veritas.Gates

open Veritas

/-- Absolute |correlation| between two assets. Same-asset pairs → 1
    (even without an explicit entry); unknown cross-asset pairs → 0. -/
def correlationBetween
    (table : List CorrelationEntry) (a b : String) : Rat :=
  if a == b then 1
  else
    match table.find?
      (fun e => (e.assetA == a && e.assetB == b)
              ∨ (e.assetA == b && e.assetB == a)) with
    | some e => |e.coefficient|
    | none   => 0

/-- Sum of each existing position's absolute notional weighted by
    |correlation| with the proposed asset. -/
def correlationAdjustedExposure
    (port : Portfolio) (p : TradeProposal) : Rat :=
  port.positions.foldl
    (fun acc pos =>
      acc +
      |pos.entryPrice * pos.size| *
        correlationBetween port.correlations pos.asset p.asset)
    0

/-- Does any existing position on the same asset carry the opposite
    direction? Cross-asset opposite directions are not a conflict. -/
def hasDirectionConflict
    (positions : List Position) (p : TradeProposal) : Bool :=
  positions.any
    (fun pos => pos.asset == p.asset && pos.direction != p.direction)

/-- Gate 3: check portfolio interference under correlation weighting. -/
def checkPortfolio
    (p : TradeProposal) (port : Portfolio) (equity : Rat) : Verdict :=
  if hasDirectionConflict port.positions p then
    .Reject ["direction_conflicts_existing_position"]
  else
    let adjusted := correlationAdjustedExposure port p
    let cap := equity * port.maxGrossExposureFraction
    let proposed := |p.notionalUsd|
    let total := adjusted + proposed
    if cap ≤ 0 then
      .Reject ["gross_exposure_cap_non_positive"]
    else if total ≤ cap then
      .Approve
    else
      let headroom := cap - adjusted
      if headroom ≤ 0 then
        .Reject ["portfolio_already_at_correlation_weighted_cap"]
      else
        .Resize headroom

-- ── Soundness contract ────────────────────────────────────────────

/-- Gate 3 soundness (approve path): correlation-adjusted exposure
    plus the proposal's absolute notional stays within the cap. -/
theorem checkPortfolio_approve_respects_cap
    (p : TradeProposal) (port : Portfolio) (equity : Rat)
    (h : checkPortfolio p port equity = .Approve) :
    correlationAdjustedExposure port p + |p.notionalUsd|
      ≤ equity * port.maxGrossExposureFraction := by
  have h' :
      (if hasDirectionConflict port.positions p then
        Verdict.Reject ["direction_conflicts_existing_position"]
       else if equity * port.maxGrossExposureFraction ≤ 0 then
        Verdict.Reject ["gross_exposure_cap_non_positive"]
       else if correlationAdjustedExposure port p + |p.notionalUsd|
              ≤ equity * port.maxGrossExposureFraction then
        Verdict.Approve
       else if equity * port.maxGrossExposureFraction
               - correlationAdjustedExposure port p ≤ 0 then
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
