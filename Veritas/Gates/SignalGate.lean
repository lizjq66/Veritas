/-
  Veritas.Gates.SignalGate — Gate 1: signal / assumption consistency.

  Given a proposed trade and the market context it was formed under,
  Gate 1 runs every strategy in the policy registry, collects the
  firing signals, and verifies that:

    1. At least one strategy fires on this context.
    2. All firing strategies agree on direction
       (MutuallyConsistent — the v0.2 addition).
    3. The proposal's direction matches the firing strategies'.
    4. The combined assumption list is non-empty.

  This gate does not know about capital or risk. Those belong to Gate 2.
-/
import Veritas.Gates.Types
import Veritas.Strategy.Registry

namespace Veritas.Gates

open Veritas Veritas.Strategy

/-- Build the market snapshot a proposal is implicitly referencing. -/
def snapshotOf (p : TradeProposal) : MarketSnapshot :=
  ⟨p.fundingRate, p.price, p.timestamp, p.openInterest, p.spotPrice, p.liquidations24h⟩

/-- Gate 1: check signal consistency across the policy registry.

    Execution order inside the gate:
      - Collect every firing strategy's signal.
      - If the set is empty → reject (no policy fires on this context).
      - If firing strategies disagree → reject (policies contradict).
      - If the (agreed) direction disagrees with the proposal → reject.
      - If the resulting assumption list is empty → reject.
      - Otherwise approve, attaching the union of assumptions from
        all firing strategies whose direction matches the proposal. -/
def verifySignal (p : TradeProposal) : Verdict × List Assumption :=
  match firingSignals (snapshotOf p) with
  | [] =>
    (.Reject ["no_signal_under_policy"], [])
  | s :: rest =>
    if mutuallyConsistent (s :: rest) then
      if s.direction == p.direction then
        match attachedAssumptions (snapshotOf p) p.direction with
        | []      => (.Reject ["malformed_proposal_no_assumptions"], [])
        | a :: as => (.Approve, a :: as)
      else
        (.Reject ["direction_conflicts_with_signal"], [])
    else
      (.Reject ["strategies_contradict"], [])

-- ── Soundness contract ────────────────────────────────────────────

/-- Signal-consistency predicate. A proposal is signal-consistent when
    the policy registry fires at least one strategy on the submitted
    context, those firing strategies are mutually consistent on
    direction, the proposal's direction agrees with them, and the
    combined assumption list is non-empty.

    This is the meaning of a Gate 1 approval, stated as a Prop so
    downstream reasoning can quote it directly. -/
def signalConsistent (p : TradeProposal) : Prop :=
  let snap := snapshotOf p
  ∃ s : Signal,
    s ∈ firingSignals snap
    ∧ MutuallyConsistent (firingSignals snap)
    ∧ s.direction = p.direction
    ∧ attachedAssumptions snap p.direction ≠ []

/-- Gate 1 soundness: if `verifySignal` approves a proposal, then the
    proposal satisfies `signalConsistent` against the policy registry.

    This is the v0.2 upgrade of the v0.1 theorem: in v0.1 the
    registry had one entry and the theorem degenerated to "direction
    matches that one entry"; now the theorem captures genuine
    multi-policy consistency. -/
theorem verifySignal_approve_implies_consistent
    (p : TradeProposal)
    (h : (verifySignal p).1 = .Approve) :
    signalConsistent p := by
  -- Unfold verifySignal at h so the match on firingSignals is visible.
  unfold verifySignal at h
  -- Case on what the registry emitted for this snapshot.
  cases hsig : firingSignals (snapshotOf p) with
  | nil =>
    -- firingSignals = []  →  verifySignal = (.Reject _, [])  →  h is a contradiction.
    rw [hsig] at h
    cases h
  | cons s rest =>
    rw [hsig] at h
    by_cases hmc : mutuallyConsistent (s :: rest) = true
    · -- Strategies agree on direction.
      simp only [hmc, if_true] at h
      by_cases hdir : (s.direction == p.direction) = true
      · simp only [hdir, if_true] at h
        -- Inspect assumption list.
        cases hlist : attachedAssumptions (snapshotOf p) p.direction with
        | nil =>
          rw [hlist] at h; cases h
        | cons x xs =>
          -- Approve branch. Build witness for signalConsistent.
          refine ⟨s, ?_, ?_, ?_, ?_⟩
          · -- s ∈ firingSignals (snapshotOf p)
            rw [hsig]; exact List.Mem.head rest
          · -- MutuallyConsistent (firingSignals ...)
            unfold MutuallyConsistent; rw [hsig]; exact hmc
          · -- s.direction = p.direction  (from hdir : (==) = true)
            cases hs : s.direction <;> cases hp : p.direction
            · rfl
            · rw [hs, hp] at hdir; cases hdir
            · rw [hs, hp] at hdir; cases hdir
            · rfl
          · rw [hlist]; exact List.cons_ne_nil x xs
      · -- Directions disagree → reject.
        simp only [hdir, if_false] at h
        cases h
    · -- Strategies disagree → reject.
      have hmcf : mutuallyConsistent (s :: rest) = false := by
        cases hval : mutuallyConsistent (s :: rest)
        · rfl
        · exact absurd hval hmc
      simp only [hmcf, if_false] at h
      cases h

end Veritas.Gates
