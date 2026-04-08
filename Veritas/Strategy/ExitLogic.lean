/-
  Veritas.Strategy.ExitLogic — Monitor and exit decision.

  Three checks in strict order:
    1. Assumption met → funding reverted to normal
    2. Assumption broke → held too long, funding didn't revert
    3. Stop loss → price moved against us past threshold

  The ordering matters: assumption-level exits take priority over
  mechanical stop-loss. This is the Veritas philosophy — we exit
  because our thesis resolved, not just because a number crossed a line.
-/
import Veritas.Types

namespace Veritas.Strategy

open Veritas

/-- Reversion target: |funding| < 0.01%/hr = 0.0001. -/
def reversionTarget : Float := 0.0001

/-- Maximum hold time in seconds (8 hours). -/
def maxHoldSeconds : Nat := 8 * 3600

/-- Step 7: Monitor — should we exit?
    Checks in order: assumption_met, assumption_broke, stop_loss. -/
def checkExit (snapshot : MarketSnapshot) (position : Position) : ExitDecision :=
  -- 1. Assumption met: funding rate reverted below target
  if Float.abs snapshot.fundingRate < reversionTarget then
    { shouldExit := true, reason := some .AssumptionMet }
  -- 2. Assumption broke: held past max time without reversion
  else if snapshot.timestamp ≥ position.entryTimestamp + maxHoldSeconds then
    { shouldExit := true, reason := some .AssumptionBroke }
  -- 3. Stop loss: price moved against us
  else
    let pnlPct := match position.direction with
      | .Long  => (snapshot.btcPrice - position.entryPrice) / position.entryPrice * 100.0
      | .Short => (position.entryPrice - snapshot.btcPrice) / position.entryPrice * 100.0
    if pnlPct ≤ -position.stopLossPct then
      { shouldExit := true, reason := some .StopLoss }
    else
      { shouldExit := false, reason := none }

/-- Every exit is classified into exactly one of three reasons.
    This is the Veritas invariant enforced by the ExitReason sum type. -/
theorem exitReason_exhaustive (snapshot : MarketSnapshot) (position : Position) :
    let d := checkExit snapshot position
    d.shouldExit = false ∨ d.reason.isSome = true := by
  simp only [checkExit]
  split
  · right; rfl
  · split
    · right; rfl
    · split <;> split
      · right; rfl
      · left; rfl
      · right; rfl
      · left; rfl

end Veritas.Strategy
