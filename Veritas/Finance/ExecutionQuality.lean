/-
  Veritas.Finance.ExecutionQuality — Execution quality metrics.

  Pure functions that decompose trade outcome into signal accuracy
  vs execution quality.

  v0.2 Slice 5: migrated to exact `Rat` arithmetic.
-/
import Veritas.Types
import Mathlib.Data.Rat.Defs
import Mathlib.Algebra.Order.Ring.Abs
import Mathlib.Algebra.Order.Ring.Rat

namespace Veritas.Finance

open Veritas

/-- Slippage in basis points: |fill - mark| / mark * 10000. -/
def slippageBps (markPrice fillPrice : Rat) : Rat :=
  if markPrice > 0 then |fillPrice - markPrice| / markPrice * 10000
  else 0

/-- Price impact in basis points: |exit - entry_mark| / entry_mark * 10000. -/
def priceImpactBps (entryMarkPrice exitPrice : Rat) : Rat :=
  if entryMarkPrice > 0 then |exitPrice - entryMarkPrice| / entryMarkPrice * 10000
  else 0

/-- Ratio of realized PnL to expected PnL. Returns 1 if expected is zero. -/
def realizedVsExpectedPnl (realizedPnl expectedPnl : Rat) : Rat :=
  if expectedPnl = 0 then 1
  else realizedPnl / expectedPnl

/-- Whether the signal direction was correct, based on exit reason. -/
def signalCorrect (reason : ExitReason) : Bool :=
  match reason with
  | .AssumptionMet  => true
  | .AssumptionBroke => false
  | .StopLoss       => false

end Veritas.Finance
