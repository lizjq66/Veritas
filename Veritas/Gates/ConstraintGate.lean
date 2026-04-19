/-
  Veritas.Gates.ConstraintGate — Gate 2: strategy-constraint compatibility.

  Given a proposed trade and the caller's account constraints, decide
  whether the trade is allowed at its requested size. The verifier may:

    - APPROVE the trade unchanged
    - RESIZE it downward to fit within the reliability-adjusted ceiling
    - REJECT it if no non-zero size is permissible

  Gate 2 is Veritas's strongest formal property in v0.1: any value it
  approves or resizes to is bounded by `calculatePositionSize`, which
  in turn carries five theorems in `Veritas.Finance.PositionSizing`
  (nonneg, 25%-capped, zero-at-no-edge, monotone in reliability,
  exploration-capped at 1%).

  Gate 2 does not know about portfolio state. That belongs to Gate 3.
-/
import Veritas.Gates.Types
import Veritas.Finance.PositionSizing

namespace Veritas.Gates

open Veritas Veritas.Finance

/-- Gate 2: check that the proposed notional fits within the account's
    reliability-adjusted ceiling.

    The allowed ceiling is `calculatePositionSize(equity, reliability, samples)`,
    whose bounds are formally proved in Finance.PositionSizing. -/
def checkConstraints (p : TradeProposal) (c : AccountConstraints) : Verdict :=
  let allowed := calculatePositionSize c.equity c.reliability c.sampleSize
  if c.maxLeverage <= 0.0 then
    .Reject ["leverage_cap_non_positive"]
  else if allowed <= 0.0 then
    .Reject ["no_edge_reliability_below_threshold"]
  else if p.notionalUsd <= 0.0 then
    .Reject ["proposal_notional_non_positive"]
  else if p.notionalUsd <= allowed then
    .Approve
  else
    .Resize allowed

end Veritas.Gates
