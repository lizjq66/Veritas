/-
  Veritas.Strategy.Registry — Policy registry for v0.2+.

  A `Strategy` is a named triple: decider, assumption extractor, and
  the name the gate surfaces to callers. The registry is the list of
  all strategies Veritas knows about.

  Gate 1 dispatches over this registry. For every submitted
  `TradeProposal`, Gate 1 runs every strategy's decider on the
  submitted context, collects the set of firing signals, and checks
  that they are mutually consistent (all agree on direction) before
  approving.

  v0.2 registers two built-in strategies: `funding_reversion` and
  `basis_reversion`. v0.3 will open this list to external plugin
  registration.
-/
import Veritas.Types
import Veritas.Strategy.FundingReversion
import Veritas.Strategy.BasisReversion
import Veritas.Strategy.LiquidationCascade

namespace Veritas.Strategy

open Veritas

/-- A policy the Gate 1 dispatcher knows how to run. -/
structure Strategy where
  name : String
  decide : MarketSnapshot → Option Signal
  extractAssumptions : Signal → List Assumption

/-- The built-in policy registry. -/
def allStrategies : List Strategy := [
  { name := "funding_reversion"
  , decide := Veritas.Strategy.decide
  , extractAssumptions := Veritas.Strategy.extractAssumptions },
  { name := "basis_reversion"
  , decide := Veritas.Strategy.decideBasis
  , extractAssumptions := Veritas.Strategy.extractBasisAssumptions },
  { name := "liq_cascade_reversion"
  , decide := Veritas.Strategy.decideCascade
  , extractAssumptions := Veritas.Strategy.extractCascadeAssumptions }
]

/-- Every signal emitted by any strategy in the registry on the given
    market snapshot. Strategies that do not fire contribute nothing. -/
def firingSignals (snap : MarketSnapshot) : List Signal :=
  allStrategies.filterMap (fun s => s.decide snap)

/-- Two signals are compatible when they share a direction. -/
def signalsCompatible (s t : Signal) : Bool :=
  s.direction == t.direction

/-- All signals in the list share a direction.

    v0.2 uses the simplest possible consistency criterion: any two
    firing strategies must agree on direction. Richer notions
    (cross-asset correlation, quantitative conflict scoring) are
    v0.3+ work. -/
def mutuallyConsistent : List Signal → Bool
  | []      => true
  | s :: ss => ss.all (fun t => signalsCompatible s t)

/-- Propositional form used in theorem statements. -/
def MutuallyConsistent (signals : List Signal) : Prop :=
  mutuallyConsistent signals = true

/-- Union of assumptions attached by every firing strategy whose
    signal direction matches `dir`. Used by Gate 1 to populate the
    certificate with all assumptions the caller is implicitly
    committing to. -/
def attachedAssumptions (snap : MarketSnapshot) (dir : Direction) : List Assumption :=
  allStrategies.foldl
    (fun acc s =>
      match s.decide snap with
      | some sig =>
        if sig.direction == dir then acc ++ s.extractAssumptions sig
        else acc
      | none => acc)
    []

end Veritas.Strategy
