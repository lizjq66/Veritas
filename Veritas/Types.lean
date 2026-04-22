/-
  Veritas.Types — Core type definitions.

  All decision-relevant types live here. Python I/O shell only sees
  these types through JSON serialization via the veritas-core binary.
-/

namespace Veritas

/-- Trading direction. -/
inductive Direction where
  | Long
  | Short
  deriving Repr, BEq, Inhabited, DecidableEq

/-- Why a position was closed. Every exit MUST be classified — this is
    the Veritas philosophy enforced at the type level. -/
inductive ExitReason where
  | AssumptionMet
  | AssumptionBroke
  | StopLoss
  deriving Repr, BEq, Inhabited, DecidableEq

/-- Market regime — first-pass classifier (v0.1: hand-coded from 24h price change).
    See python/regime.py for the classifier implementation. -/
inductive Regime where
  | Bull
  | Bear
  | Choppy
  | Unknown
  deriving Repr, BEq, Inhabited, DecidableEq

/-- A snapshot of market state at a point in time.

    `btcPrice` is the perp mark price. `spotPrice` is the concurrent
    spot price on the reference venue (e.g. Coinbase / Binance spot).
    Strategies that do not care about the spot leg can leave
    `spotPrice` at its default of 0 — Veritas treats 0 as "spot
    unknown" and strategies such as BasisReversion explicitly
    refuse to fire on missing spot. -/
structure MarketSnapshot where
  fundingRate : Float
  btcPrice : Float
  timestamp : Nat
  openInterest : Float := 0.0
  spotPrice : Float := 0.0
  deriving Repr, Inhabited

/-- A trading signal produced by the decision engine. -/
structure Signal where
  direction : Direction
  fundingRate : Float
  price : Float
  deriving Repr, Inhabited

/-- An explicit assumption underlying a trade. -/
structure Assumption where
  name : String
  description : String
  deriving Repr, BEq, Inhabited

/-- An assumption enriched with its historical reliability score. -/
structure AssumptionWithReliability where
  assumption : Assumption
  reliability : Float
  deriving Repr, Inhabited

/-- An open position. -/
structure Position where
  direction : Direction
  entryPrice : Float
  size : Float
  leverage : Float
  stopLossPct : Float
  entryTimestamp : Nat
  assumptionName : String
  deriving Repr, Inhabited

/-- The result of monitoring: should we exit, and why? -/
structure ExitDecision where
  shouldExit : Bool
  reason : Option ExitReason
  deriving Repr, Inhabited

-- ── Serialization helpers ──────────────────────────────────────────

namespace Direction

def toString : Direction → String
  | .Long  => "LONG"
  | .Short => "SHORT"

def fromString? : String → Option Direction
  | "LONG"  => some .Long
  | "SHORT" => some .Short
  | _       => none

def opposite : Direction → Direction
  | .Long  => .Short
  | .Short => .Long

end Direction

namespace ExitReason

def toString : ExitReason → String
  | .AssumptionMet   => "assumption_met"
  | .AssumptionBroke  => "assumption_broke"
  | .StopLoss        => "stop_loss"

def fromString? : String → Option ExitReason
  | "assumption_met"   => some .AssumptionMet
  | "assumption_broke" => some .AssumptionBroke
  | "stop_loss"        => some .StopLoss
  | _                  => none

end ExitReason

end Veritas
