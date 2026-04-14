/-
  Veritas.Finance.ExecutionQuality — Execution quality metrics.

  Pure functions that decompose trade outcome into signal accuracy
  vs execution quality. No I/O — these belong in the verified core.
-/
import Veritas.Types

namespace Veritas.Finance

open Veritas

/-- Slippage in basis points: |fill - mark| / mark * 10000. -/
def slippageBps (markPrice fillPrice : Float) : Float :=
  if markPrice > 0.0 then Float.abs (fillPrice - markPrice) / markPrice * 10000.0
  else 0.0

/-- Price impact in basis points: |exit - entry_mark| / entry_mark * 10000. -/
def priceImpactBps (entryMarkPrice exitPrice : Float) : Float :=
  if entryMarkPrice > 0.0 then Float.abs (exitPrice - entryMarkPrice) / entryMarkPrice * 10000.0
  else 0.0

/-- Ratio of realized PnL to expected PnL. Returns 1.0 if expected is zero. -/
def realizedVsExpectedPnl (realizedPnl expectedPnl : Float) : Float :=
  if expectedPnl == 0.0 then 1.0
  else realizedPnl / expectedPnl

/-- Whether the signal direction was correct, based on exit reason.
    assumption_met → signal was correct.
    assumption_broke / stop_loss → signal was wrong. -/
def signalCorrect (reason : ExitReason) : Bool :=
  match reason with
  | .AssumptionMet  => true
  | .AssumptionBroke => false
  | .StopLoss       => false

end Veritas.Finance
