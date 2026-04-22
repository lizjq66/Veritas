/-
  Veritas.Gates.ConstraintGate — Gate 2: strategy-constraint compatibility.

  Given a proposed trade and the caller's account constraints, decide
  whether the trade is allowed at its requested size. The verifier may:
    - APPROVE the trade unchanged
    - RESIZE it downward to fit within the reliability-adjusted ceiling
    - REJECT it if no non-zero size is permissible

  Gate 2 is Veritas's strongest formal property: any value it approves
  or resizes to is bounded by `calculatePositionSize`, which carries
  five theorems in `Veritas.Finance.PositionSizing`. In v0.2 Slice 5
  the whole arithmetic stack runs on exact `Rat` — no Float axioms.

  Gate 2 does not know about portfolio state. That belongs to Gate 3.
-/
import Veritas.Gates.Types
import Veritas.Finance.PositionSizing

namespace Veritas.Gates

open Veritas Veritas.Finance

/-- Gate 2: check that the proposed notional fits within the account's
    reliability-adjusted ceiling. -/
def checkConstraints (p : TradeProposal) (c : AccountConstraints) : Verdict :=
  let allowed := calculatePositionSize c.equity c.reliability c.sampleSize
  if c.maxLeverage ≤ 0 then
    .Reject ["leverage_cap_non_positive"]
  else if allowed ≤ 0 then
    .Reject ["no_edge_reliability_below_threshold"]
  else if p.notionalUsd ≤ 0 then
    .Reject ["proposal_notional_non_positive"]
  else if p.notionalUsd ≤ allowed then
    .Approve
  else
    .Resize allowed

-- ── Soundness contracts ───────────────────────────────────────────

theorem checkConstraints_approve_within_ceiling
    (p : TradeProposal) (c : AccountConstraints)
    (h : checkConstraints p c = .Approve) :
    p.notionalUsd ≤ calculatePositionSize c.equity c.reliability c.sampleSize := by
  have h' :
      (if c.maxLeverage ≤ 0 then
        Verdict.Reject ["leverage_cap_non_positive"]
       else if calculatePositionSize c.equity c.reliability c.sampleSize ≤ 0 then
        Verdict.Reject ["no_edge_reliability_below_threshold"]
       else if p.notionalUsd ≤ 0 then
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

theorem checkConstraints_resize_respects_ceiling
    (p : TradeProposal) (c : AccountConstraints) (n : Rat)
    (h : checkConstraints p c = .Resize n) :
    n ≤ calculatePositionSize c.equity c.reliability c.sampleSize := by
  have h' :
      (if c.maxLeverage ≤ 0 then
        Verdict.Reject ["leverage_cap_non_positive"]
       else if calculatePositionSize c.equity c.reliability c.sampleSize ≤ 0 then
        Verdict.Reject ["no_edge_reliability_below_threshold"]
       else if p.notionalUsd ≤ 0 then
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
        · injection h' with hn
          rw [← hn]

end Veritas.Gates
