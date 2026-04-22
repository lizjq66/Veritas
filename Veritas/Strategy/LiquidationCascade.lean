/-
  Veritas.Strategy.LiquidationCascade — Decider + assumption extractor.

  The third strategy: post-cascade mean reversion. After a large
  liquidation wave, price tends to bounce back opposite to the
  forced-selling direction as the squeezed positions unwind.

  Signal direction flips the liquidation sign:
    liquidations24h > +threshold  →  shorts stopped out in a surge
                                      →  SHORT perp (expect revert down)
    liquidations24h < -threshold  →  longs stopped out in a crash
                                      →  LONG perp (expect revert up)

  The cascade magnitude is a crude proxy — net signed USD flow — but
  sufficient for Gate 1 multi-policy consistency checks: liquidation
  cascades and funding-rate extremes frequently co-occur and can give
  aligned or opposite signals, which is exactly the case Gate 1
  needs to arbitrate.

  This module is standalone and registered in `Strategy.Registry`.
-/
import Veritas.Types
import Mathlib.Data.Rat.Defs
import Mathlib.Algebra.Order.Ring.Abs
import Mathlib.Algebra.Order.Ring.Rat

namespace Veritas.Strategy

open Veritas

/-- Liquidation-cascade threshold: 50 million USD of net signed flow
    in the last 24 hours. Calibrated for BTC perp scales; callers
    with smaller venues should override via registry substitution. -/
def cascadeThreshold : Rat := 50000000

/-- Decide: did a cascade just finish and should we fade it?
    Refuses to fire when liquidation data is absent (= 0). -/
def decideCascade (snapshot : MarketSnapshot) : Option Signal :=
  let liq := snapshot.liquidations24h
  if liq = 0 then none
  else if |liq| > cascadeThreshold then
    -- Positive liquidations (shorts stopped) → SHORT perp.
    -- Negative liquidations (longs stopped) → LONG perp.
    let dir := if liq > 0 then Direction.Short else Direction.Long
    some { direction := dir, fundingRate := snapshot.fundingRate,
           price := snapshot.btcPrice }
  else
    none

/-- Declare: what are we betting on when the cascade signal fires? -/
def extractCascadeAssumptions (_signal : Signal) : List Assumption :=
  [{ name := "price_reverts_after_liquidation_cascade_within_4h"
   , description :=
       "After |liquidations24h| exceeds $50M on Hyperliquid BTC perp, " ++
       "price reverts at least halfway toward the pre-cascade level " ++
       "within 4 hours."
   }]

end Veritas.Strategy
