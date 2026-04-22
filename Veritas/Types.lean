/-
  Veritas.Types — Core type definitions.

  All decision-relevant types live here. Python I/O shell only sees
  these types through JSON serialization via the veritas-core binary.

  v0.2 Slice 5: all numeric fields migrated from `Float` to `Rat`
  (exact rationals). Mathlib's ordered-field lemmas replace the
  Float axioms that the pre-Slice-5 proofs depended on.
-/
import Mathlib.Data.Rat.Defs

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

/-- Market regime — first-pass classifier (v0.1: hand-coded from 24h price change). -/
inductive Regime where
  | Bull
  | Bear
  | Choppy
  | Unknown
  deriving Repr, BEq, Inhabited, DecidableEq

/-- A snapshot of market state at a point in time.

    All numeric fields are exact `Rat` (v0.2 Slice 5). CLI input
    parses decimal strings like `"0.0012"` directly into `Rat`. -/
structure MarketSnapshot where
  fundingRate : Rat
  btcPrice : Rat
  timestamp : Nat
  openInterest : Rat := 0
  spotPrice : Rat := 0
  deriving Repr, Inhabited

/-- A trading signal produced by the decision engine. -/
structure Signal where
  direction : Direction
  fundingRate : Rat
  price : Rat
  deriving Repr, Inhabited

/-- An explicit assumption underlying a trade. -/
structure Assumption where
  name : String
  description : String
  deriving Repr, BEq, Inhabited

/-- An assumption enriched with its historical reliability score. -/
structure AssumptionWithReliability where
  assumption : Assumption
  reliability : Rat
  deriving Repr, Inhabited

/-- An open position. `asset` identifies the underlying symbol. -/
structure Position where
  direction : Direction
  entryPrice : Rat
  size : Rat
  leverage : Rat
  stopLossPct : Rat
  entryTimestamp : Nat
  assumptionName : String
  asset : String := ""
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
