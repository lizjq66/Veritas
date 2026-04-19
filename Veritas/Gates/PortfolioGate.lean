/-
  Veritas.Gates.PortfolioGate — Gate 3: portfolio interference.

  Given the caller's existing positions and a new proposed trade,
  decide whether adding the trade would violate portfolio-level
  constraints.

  v0.1 scope is deliberately narrow:

    - CONFLICT: a new position in the opposite direction of any existing
      position is a policy-level conflict (v0.1 runs one asset at a time,
      so any existing position is implicitly on the same asset).
    - CONCENTRATION: gross notional across all positions (including the
      new one) must not exceed `maxGrossExposureFraction` × equity. If
      the new trade would breach this, Gate 3 resizes to the remaining
      headroom.
    - CORRELATION: v0.1 treats all positions as fully correlated. True
      multi-asset correlation is a v0.2 concern.

  Gate 3 only returns APPROVE / RESIZE / REJECT with explicit reason
  codes. It never silently adjusts a trade.
-/
import Veritas.Gates.Types

namespace Veritas.Gates

open Veritas

/-- Sum of absolute-value notionals across existing positions, in USD. -/
def grossNotional (positions : List Position) : Float :=
  positions.foldl (fun acc p => acc + Float.abs (p.entryPrice * p.size)) 0.0

/-- Does the proposal direction conflict with any existing position? -/
def hasDirectionConflict (positions : List Position) (p : TradeProposal) : Bool :=
  positions.any (fun pos => pos.direction != p.direction)

/-- Gate 3: check portfolio interference. -/
def checkPortfolio (p : TradeProposal) (port : Portfolio) (equity : Float) : Verdict :=
  if hasDirectionConflict port.positions p then
    .Reject ["direction_conflicts_existing_position"]
  else
    let existingGross := grossNotional port.positions
    let cap := equity * port.maxGrossExposureFraction
    let proposed := Float.abs p.notionalUsd
    let total := existingGross + proposed
    if cap <= 0.0 then
      .Reject ["gross_exposure_cap_non_positive"]
    else if total <= cap then
      .Approve
    else
      let headroom := cap - existingGross
      if headroom <= 0.0 then
        .Reject ["portfolio_already_at_gross_exposure_cap"]
      else
        .Resize headroom

end Veritas.Gates
