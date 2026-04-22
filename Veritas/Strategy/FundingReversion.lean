/-
  Veritas.Strategy.FundingReversion — Decider + assumption extractor.

  The first strategy for v0.1: funding rate mean reversion on BTC perps.
  When |funding_rate| exceeds a threshold, bet that it reverts.

  v0.2 Slice 5: arithmetic migrated to exact `Rat`.
-/
import Veritas.Types
import Mathlib.Data.Rat.Defs
import Mathlib.Algebra.Order.Ring.Abs
import Mathlib.Algebra.Order.Ring.Rat

namespace Veritas.Strategy

open Veritas

/-- Funding rate threshold: 0.05 %/hr = 1/2000 as an exact rational. -/
def fundingThreshold : Rat := 1 / 2000

/-- Step 2: Decide — should we trade?
    If |funding_rate| > threshold, emit a signal to go against the crowd.
    Positive funding → shorts pay longs → go LONG (funding will revert down).
    Negative funding → longs pay shorts → go SHORT (funding will revert up). -/
def decide (snapshot : MarketSnapshot) : Option Signal :=
  let rate := snapshot.fundingRate
  if |rate| > fundingThreshold then
    let dir := if rate > 0 then Direction.Long else Direction.Short
    some { direction := dir, fundingRate := rate, price := snapshot.btcPrice }
  else
    none

/-- Step 3: Declare — what are we betting on?
    v0.1 hardcodes a single assumption. v0.2 will use LLM extraction. -/
def extractAssumptions (_signal : Signal) : List Assumption :=
  [{ name := "funding_rate_reverts_within_8h"
   , description :=
       s!"When |funding_rate| > 0.05%/hr on Hyperliquid BTC perp, " ++
       "it returns to |funding_rate| < 0.01%/hr within 8 hours."
   }]

end Veritas.Strategy
