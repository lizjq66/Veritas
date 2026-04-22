/-
  Veritas.Gates.Types — Shared types for the three-gate verifier.

  A trade proposal enters the verifier; a verdict comes out. The
  intermediate types are pure data, serializable across the Python/Lean
  boundary.
-/
import Veritas.Types

namespace Veritas.Gates

open Veritas

/-- A proposed trade: direction, intended notional size in USD, and the
    market context the proposal was formed under. No assumption is
    attached yet — Gate 1 is responsible for attaching those. -/
structure TradeProposal where
  direction : Direction
  notionalUsd : Float
  fundingRate : Float
  price : Float
  timestamp : Nat
  openInterest : Float := 0.0
  spotPrice : Float := 0.0
  /-- Asset symbol. Used by Gate 3 correlation weighting. Default ""
      means "same bucket as every other default-asset position" —
      preserves v0.1 single-asset behavior. -/
  asset : String := ""
  deriving Repr, Inhabited

/-- Account-level constraints a proposal must satisfy.
    All fields are policy inputs, not derived from market state. -/
structure AccountConstraints where
  /-- Current account equity in USD. -/
  equity : Float
  /-- Maximum fraction of equity any one position may consume
      (Veritas hard-caps this at 0.25 regardless of input). -/
  maxPositionFraction : Float
  /-- Maximum leverage allowed by policy. -/
  maxLeverage : Float
  /-- Stop-loss percentage that will be applied to any approved trade. -/
  stopLossPct : Float
  /-- Reliability of the assumption behind the proposal (0.0–1.0). -/
  reliability : Float
  /-- Number of historical samples backing the reliability score. -/
  sampleSize : Nat
  deriving Repr, Inhabited

/-- One entry in the portfolio correlation table. The absolute value
    of `coefficient` (clamped to [0, 1]) is used by Gate 3: a zero
    means "these two assets share no risk factor"; a one means "these
    two assets are a single risk factor". Sign is ignored in v0.2
    because Gate 3 measures exposure magnitude, not directional
    hedges; directional correlation lives in v0.3+ work. -/
structure CorrelationEntry where
  assetA : String
  assetB : String
  coefficient : Float
  deriving Repr, Inhabited

/-- A portfolio snapshot plus the correlation information Gate 3
    needs to measure exposure across assets.

    `correlations` defaults to an empty list. In that case Gate 3's
    correlation function falls back to the single-asset default:
    same asset → 1.0, different assets → 0.0. -/
structure Portfolio where
  positions : List Position
  /-- Maximum total correlation-weighted exposure allowed across the
      portfolio, as a fraction of equity. -/
  maxGrossExposureFraction : Float
  correlations : List CorrelationEntry := []
  deriving Repr, Inhabited

/-- Verdict a gate can return. -/
inductive Verdict where
  /-- Proposal passes this gate without modification. -/
  | Approve
  /-- Proposal passes only if resized to `newNotionalUsd`. -/
  | Resize (newNotionalUsd : Float)
  /-- Proposal is rejected. The string list carries machine-readable reason codes. -/
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

def resizedNotional? : Verdict → Option Float
  | .Resize n => some n
  | _         => none

def reasonCodes : Verdict → List String
  | .Reject cs => cs
  | _          => []

end Verdict

/-- Full verification trace across all three gates. This is what the
    verifier returns, and what `emit-certificate` serializes. -/
structure Certificate where
  gate1 : Verdict
  gate2 : Verdict
  gate3 : Verdict
  /-- Assumptions attached by Gate 1. -/
  assumptions : List Assumption
  /-- Final approved notional (after any Gate 2/3 resize), or 0.0 if rejected. -/
  finalNotionalUsd : Float
  deriving Repr, Inhabited

namespace Certificate

/-- A certificate approves the trade iff every gate approves or resizes,
    and at least one non-reject verdict is present. -/
def approves (c : Certificate) : Bool :=
  !c.gate1.isReject && !c.gate2.isReject && !c.gate3.isReject

end Certificate

end Veritas.Gates
