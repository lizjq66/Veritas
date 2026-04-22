/-
  Veritas.Strategy.BasisReversion — Decider + assumption extractor.

  The second strategy (v0.2 Slice 1): basis mean reversion on BTC perps.
  When the perp trades at a meaningful premium or discount to spot,
  bet that the basis reverts toward zero.

  v0.2 Slice 5: arithmetic migrated to exact `Rat`.
-/
import Veritas.Types
import Mathlib.Data.Rat.Defs
import Mathlib.Algebra.Order.Ring.Abs
import Mathlib.Algebra.Order.Ring.Rat

namespace Veritas.Strategy

open Veritas

/-- Basis threshold: 0.20 % (20 bps) of spot, as an exact rational. -/
def basisThreshold : Rat := 1 / 500

/-- Basis as a fraction of spot: `(perp − spot) / spot`. Returns 0
    when `spot ≤ 0` (treated as "spot unknown"). -/
def basisFraction (perpPrice spotPrice : Rat) : Rat :=
  if spotPrice > 0 then (perpPrice - spotPrice) / spotPrice
  else 0

/-- Decide: should we trade basis reversion on this snapshot?
    Fires only when spot is present and |basis| exceeds threshold. -/
def decideBasis (snapshot : MarketSnapshot) : Option Signal :=
  let basis := basisFraction snapshot.btcPrice snapshot.spotPrice
  if snapshot.spotPrice ≤ 0 then none
  else if |basis| > basisThreshold then
    let dir := if basis > 0 then Direction.Short else Direction.Long
    some { direction := dir, fundingRate := snapshot.fundingRate,
           price := snapshot.btcPrice }
  else
    none

/-- Declare: what are we betting on? -/
def extractBasisAssumptions (_signal : Signal) : List Assumption :=
  [{ name := "basis_reverts_within_24h"
   , description :=
       "When the BTC perp--spot basis exceeds ±0.20% on " ++
       "Hyperliquid vs the reference spot venue, it returns to " ++
       "within ±0.05% of zero inside 24 hours."
   }]

end Veritas.Strategy
