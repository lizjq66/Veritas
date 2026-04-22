/-
  Veritas.Strategy.BasisReversion — Decider + assumption extractor.

  The second strategy for v0.2: basis mean reversion on BTC perps.
  When the perp trades at a meaningful premium or discount to spot,
  bet that the basis reverts toward zero.

  Direction logic (structurally symmetric to FundingReversion but
  often opposite-directional in the same market context):
    basis > +threshold (perp rich vs spot) → SHORT perp
    basis < −threshold (perp cheap vs spot) → LONG perp

  This directional shape is deliberate: positive funding AND positive
  basis co-occur under long-side pressure, at which point this
  strategy's SHORT proposal conflicts with FundingReversion's LONG
  proposal. Gate 1's multi-policy consistency check will have a real
  job to do.

  This module is standalone. Gate 1 wiring (policy registry +
  MutuallyConsistent predicate) is Slice 2's work.
-/
import Veritas.Types

namespace Veritas.Strategy

open Veritas

/-- Basis threshold: 0.20% (20 basis points) of spot. Below this the
    perp--spot spread is noise; above it we call a reversion signal. -/
def basisThreshold : Float := 0.002

/-- Basis as a fraction of spot: `(perp − spot) / spot`. Returns 0
    when `spot ≤ 0` (treated as "spot unknown"). -/
def basisFraction (perpPrice spotPrice : Float) : Float :=
  if spotPrice > 0.0 then (perpPrice - spotPrice) / spotPrice
  else 0.0

/-- Decide: should we trade basis reversion on this snapshot?
    Fires only when spot is present and |basis| exceeds threshold. -/
def decideBasis (snapshot : MarketSnapshot) : Option Signal :=
  let basis := basisFraction snapshot.btcPrice snapshot.spotPrice
  if snapshot.spotPrice <= 0.0 then none
  else if Float.abs basis > basisThreshold then
    -- perp rich (basis positive) → short perp
    -- perp cheap (basis negative) → long perp
    let dir := if basis > 0.0 then Direction.Short else Direction.Long
    some { direction := dir, fundingRate := snapshot.fundingRate,
           price := snapshot.btcPrice }
  else
    none

/-- Declare: what are we betting on? v0.1 hardcodes one assumption
    per strategy; v0.3 will register externally. -/
def extractBasisAssumptions (_signal : Signal) : List Assumption :=
  [{ name := "basis_reverts_within_24h"
   , description :=
       "When the BTC perp--spot basis exceeds ±0.20% on " ++
       "Hyperliquid vs the reference spot venue, it returns to " ++
       "within ±0.05% of zero inside 24 hours."
   }]

end Veritas.Strategy
