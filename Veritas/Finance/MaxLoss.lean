/-
  Veritas.Finance.MaxLoss — Worst-case loss under stop-loss.

  Stub for v0.1. Will be expanded in v0.2 with tighter bounds
  and formal proofs.
-/
import Veritas.Types

namespace Veritas.Finance

open Veritas

/-- Maximum dollar loss if stop-loss triggers at `stopLossPct`% below entry. -/
def maxLossUnderStopLoss (entryPrice size stopLossPct : Float) : Float :=
  entryPrice * size * (stopLossPct / 100.0)

end Veritas.Finance
