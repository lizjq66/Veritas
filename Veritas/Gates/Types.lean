/-
  Veritas.Gates.Types — Shared types for the three-gate verifier.

  A trade proposal enters the verifier; a verdict comes out. The
  intermediate types are pure data, serializable across the Python/Lean
  boundary.

  v0.2 Slice 5: all numeric fields are exact `Rat`. The CLI parses
  decimal strings directly into `Rat` and emits JSON output via a
  `ratToFloat` conversion at the I/O boundary.
-/
import Veritas.Types
import Mathlib.Data.Rat.Defs

namespace Veritas.Gates

open Veritas

/-- A proposed trade: direction, intended notional size in USD, and
    the market context the proposal was formed under. -/
structure TradeProposal where
  direction : Direction
  notionalUsd : Rat
  fundingRate : Rat
  price : Rat
  timestamp : Nat
  openInterest : Rat := 0
  spotPrice : Rat := 0
  /-- Net 24-hour signed liquidation flow in USD. Consumed by
      `LiquidationCascade`; default 0 means "liquidation data
      unavailable" and that strategy will not fire. -/
  liquidations24h : Rat := 0
  /-- Asset symbol. Gate 3 uses this for same-asset direction checks
      and cross-asset correlation weighting. -/
  asset : String := ""
  deriving Repr, Inhabited

/-- Account-level constraints a proposal must satisfy. All numeric
    fields are policy inputs, not derived from market state. -/
structure AccountConstraints where
  equity : Rat
  maxPositionFraction : Rat
  maxLeverage : Rat
  stopLossPct : Rat
  /-- Reliability of the assumption(s) backing the proposal (0 ≤ r ≤ 1). -/
  reliability : Rat
  sampleSize : Nat
  deriving Repr, Inhabited

/-- One entry in the portfolio correlation table. Gate 3 uses
    `|coefficient|` (clamped to [0, 1]) when weighting exposure. -/
structure CorrelationEntry where
  assetA : String
  assetB : String
  coefficient : Rat
  deriving Repr, Inhabited

/-- Portfolio snapshot plus the correlation information Gate 3 needs
    for cross-asset exposure weighting. -/
structure Portfolio where
  positions : List Position
  /-- Maximum correlation-weighted exposure allowed across the
      portfolio, as a fraction of equity. -/
  maxGrossExposureFraction : Rat
  correlations : List CorrelationEntry := []
  deriving Repr, Inhabited

/-- Verdict a gate can return. -/
inductive Verdict where
  /-- Proposal passes this gate without modification. -/
  | Approve
  /-- Proposal passes only if resized to `newNotionalUsd` (exact `Rat`). -/
  | Resize (newNotionalUsd : Rat)
  /-- Proposal is rejected. Reason codes are machine-readable. -/
  | Reject (codes : List String)
  deriving Repr, Inhabited

namespace Verdict

def tag : Verdict → String
  | .Approve       => "approve"
  | .Resize _      => "resize"
  | .Reject _      => "reject"

def isApprove : Verdict → Bool
  | .Approve => true
  | _        => false

def isReject : Verdict → Bool
  | .Reject _ => true
  | _         => false

def resizedNotional? : Verdict → Option Rat
  | .Resize n => some n
  | _         => none

def reasonCodes : Verdict → List String
  | .Reject cs => cs
  | _          => []

end Verdict

/-- Full verification trace across all three gates. What the verifier
    returns and what `emit-certificate` serializes. -/
structure Certificate where
  gate1 : Verdict
  gate2 : Verdict
  gate3 : Verdict
  /-- Assumptions attached by Gate 1. -/
  assumptions : List Assumption
  /-- Final approved notional after any Gate 2/3 resize, or 0 if rejected. -/
  finalNotionalUsd : Rat
  deriving Repr, Inhabited

namespace Certificate

/-- A certificate approves the trade iff every gate approves or resizes. -/
def approves (c : Certificate) : Bool :=
  !c.gate1.isReject && !c.gate2.isReject && !c.gate3.isReject

end Certificate

end Veritas.Gates
