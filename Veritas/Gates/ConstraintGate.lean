/-
  Veritas.Gates.ConstraintGate — Gate 2: strategy-constraint compatibility.

  Given a proposed trade and the caller's account constraints, decide
  whether the trade is allowed at its requested size. The verifier may:

    - APPROVE the trade unchanged
    - RESIZE it downward to fit within the reliability-adjusted ceiling
    - REJECT it if no non-zero size is permissible

  Gate 2 is Veritas's strongest formal property in v0.1: any value it
  approves or resizes to is bounded by `calculatePositionSize`, which
  in turn carries five theorems in `Veritas.Finance.PositionSizing`
  (nonneg, 25%-capped, zero-at-no-edge, monotone in reliability,
  exploration-capped at 1%).

  Gate 2 does not know about portfolio state. That belongs to Gate 3.
-/
import Veritas.Gates.Types
import Veritas.Finance.PositionSizing

namespace Veritas.Gates

open Veritas Veritas.Finance

/-- Gate 2: check that the proposed notional fits within the account's
    reliability-adjusted ceiling.

    The allowed ceiling is `calculatePositionSize(equity, reliability, samples)`,
    whose bounds are formally proved in Finance.PositionSizing. -/
def checkConstraints (p : TradeProposal) (c : AccountConstraints) : Verdict :=
  let allowed := calculatePositionSize c.equity c.reliability c.sampleSize
  if c.maxLeverage <= 0.0 then
    .Reject ["leverage_cap_non_positive"]
  else if allowed <= 0.0 then
    .Reject ["no_edge_reliability_below_threshold"]
  else if p.notionalUsd <= 0.0 then
    .Reject ["proposal_notional_non_positive"]
  else if p.notionalUsd <= allowed then
    .Approve
  else
    .Resize allowed

-- ── Soundness contracts ───────────────────────────────────────────

/-- Gate 2 soundness (approve path): if `checkConstraints` approves
    a proposal, the proposal's notional is bounded by the reliability-
    adjusted ceiling computed by `calculatePositionSize`.

    The five `positionSize_*` theorems in `Finance.PositionSizing`
    characterize that ceiling (non-negative, 25%-capped, zero at no
    edge, monotone in reliability, exploration-capped at 1%). This
    theorem lifts the ceiling into the gate's public contract. -/
theorem checkConstraints_approve_within_ceiling
    (p : TradeProposal) (c : AccountConstraints)
    (h : checkConstraints p c = .Approve) :
    p.notionalUsd ≤ calculatePositionSize c.equity c.reliability c.sampleSize := by
  -- Rewrite `h` past `checkConstraints`'s outer `let allowed := ...`
  -- binding so that `split at` can descend into the if-chain.
  have h' :
      (if c.maxLeverage ≤ 0.0 then
        Verdict.Reject ["leverage_cap_non_positive"]
       else if calculatePositionSize c.equity c.reliability c.sampleSize ≤ 0.0 then
        Verdict.Reject ["no_edge_reliability_below_threshold"]
       else if p.notionalUsd ≤ 0.0 then
        Verdict.Reject ["proposal_notional_non_positive"]
       else if p.notionalUsd ≤ calculatePositionSize c.equity c.reliability c.sampleSize then
        Verdict.Approve
       else .Resize (calculatePositionSize c.equity c.reliability c.sampleSize))
        = .Approve := h
  split at h'
  · cases h'
  · split at h'
    · cases h'
    · split at h'
      · cases h'
      · split at h'
        · rename_i hle; exact hle
        · cases h'

/-- Gate 2 soundness (resize path): if `checkConstraints` resizes the
    proposal to notional `n`, then `n` is at most the ceiling. By
    construction `n` equals the ceiling; the ≤ form is what downstream
    callers typically need. -/
theorem checkConstraints_resize_respects_ceiling
    (p : TradeProposal) (c : AccountConstraints) (n : Float)
    (h : checkConstraints p c = .Resize n) :
    n ≤ calculatePositionSize c.equity c.reliability c.sampleSize := by
  have h' :
      (if c.maxLeverage ≤ 0.0 then
        Verdict.Reject ["leverage_cap_non_positive"]
       else if calculatePositionSize c.equity c.reliability c.sampleSize ≤ 0.0 then
        Verdict.Reject ["no_edge_reliability_below_threshold"]
       else if p.notionalUsd ≤ 0.0 then
        Verdict.Reject ["proposal_notional_non_positive"]
       else if p.notionalUsd ≤ calculatePositionSize c.equity c.reliability c.sampleSize then
        Verdict.Approve
       else .Resize (calculatePositionSize c.equity c.reliability c.sampleSize))
        = .Resize n := h
  split at h'
  · cases h'
  · split at h'
    · cases h'
    · split at h'
      · cases h'
      · split at h'
        · cases h'
        · -- else-branch returns `.Resize allowed`; injection gives allowed = n
          injection h' with hn
          rw [← hn]
          exact Float.le_refl _

end Veritas.Gates
