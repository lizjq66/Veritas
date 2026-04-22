/-
  Veritas.Finance.MaxLoss — Worst-case loss under stop-loss.

  Stub. v0.2 Slice 5: migrated to `Rat`.
-/
import Veritas.Types
import Mathlib.Data.Rat.Defs

namespace Veritas.Finance

open Veritas

/-- Maximum dollar loss if stop-loss triggers at `stopLossPct`% below entry. -/
def maxLossUnderStopLoss (entryPrice size stopLossPct : Rat) : Rat :=
  entryPrice * size * (stopLossPct / 100)

end Veritas.Finance
