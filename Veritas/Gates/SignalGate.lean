/-
  Veritas.Gates.SignalGate — Gate 1: signal / assumption consistency.

  Given a proposed trade and the market context it was formed under,
  verify that:
    1. Veritas's own policy would emit a signal in this context.
    2. The proposal direction agrees with that signal.
    3. The signal carries well-formed, non-empty assumptions.

  This gate does not know about capital or risk. Those belong to Gate 2.
-/
import Veritas.Gates.Types
import Veritas.Strategy.FundingReversion

namespace Veritas.Gates

open Veritas Veritas.Strategy

/-- Gate 1: check signal consistency.
    On approval, attaches Veritas's declared assumptions for this signal. -/
def verifySignal (p : TradeProposal) : Verdict × List Assumption :=
  let snap : MarketSnapshot :=
    ⟨p.fundingRate, p.price, p.timestamp, p.openInterest⟩
  match decide snap with
  | none =>
    (.Reject ["no_signal_under_policy"], [])
  | some s =>
    if s.direction == p.direction then
      let assumptions := extractAssumptions s
      match assumptions with
      | []      => (.Reject ["malformed_proposal_no_assumptions"], [])
      | _ :: _  => (.Approve, assumptions)
    else
      (.Reject ["direction_conflicts_with_signal"], [])

-- ── Soundness contract ────────────────────────────────────────────

/-- Signal-consistency predicate. A proposal is signal-consistent when
    Veritas's built-in decider would emit a signal for the submitted
    market context, the signal's direction matches the proposal's
    direction, and at least one assumption is attached.

    This is the meaning of a Gate 1 approval, stated as a Prop so
    downstream reasoning can quote it directly. -/
def signalConsistent (p : TradeProposal) : Prop :=
  ∃ s : Signal,
    Veritas.Strategy.decide
        ⟨p.fundingRate, p.price, p.timestamp, p.openInterest⟩ = some s
    ∧ s.direction = p.direction
    ∧ Veritas.Strategy.extractAssumptions s ≠ []

/-- Gate 1 soundness: if `verifySignal` approves a proposal, then the
    proposal satisfies `signalConsistent`.

    This lifts SignalGate's dispatch into a first-class theorem at the
    gate layer. Readers can see exactly what an Approve verdict means
    without reading through the `verifySignal` body. -/
theorem verifySignal_approve_implies_consistent
    (p : TradeProposal)
    (h : (verifySignal p).1 = .Approve) :
    signalConsistent p := by
  cases hd : Strategy.decide
      ⟨p.fundingRate, p.price, p.timestamp, p.openInterest⟩ with
  | none =>
    -- verifySignal reduces to (Reject _, []), contradicting h.
    simp [verifySignal, hd] at h
  | some s =>
    by_cases hdir : (s.direction == p.direction) = true
    · cases hlist : Strategy.extractAssumptions s with
      | nil =>
        -- verifySignal reduces to (Reject _, []), contradicting h.
        simp [verifySignal, hd, hdir, hlist] at h
      | cons x xs =>
        refine ⟨s, hd, ?_, ?_⟩
        · -- s.direction = p.direction via case split on the enum.
          cases hs : s.direction <;> cases hp : p.direction
          · rfl
          · rw [hs, hp] at hdir; cases hdir
          · rw [hs, hp] at hdir; cases hdir
          · rfl
        · rw [hlist]; exact List.cons_ne_nil x xs
    · -- Direction mismatch → Reject, contradicting h.
      simp [verifySignal, hd, hdir] at h

end Veritas.Gates
