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

/-- If Gate 2 approves, the submitted proposal is non-negative: the
    Approve branch is only reachable when `¬ (p.notionalUsd ≤ 0)`, so
    `0 < p.notionalUsd` and in particular `0 ≤ p.notionalUsd`. Used by
    the certificate-level composition theorem to feed Gate 3's resize
    helper the non-negativity it needs. -/
theorem checkConstraints_approve_implies_proposal_nonneg
    (p : TradeProposal) (c : AccountConstraints)
    (h : checkConstraints p c = .Approve) :
    0 ≤ p.notionalUsd := by
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
        · -- Approve branch. `rename_i` binds anonymous hypotheses in
          -- order of introduction (oldest first): positions are
          --   1: ¬ (maxLeverage ≤ 0)
          --   2: ¬ (calculatePositionSize ≤ 0)
          --   3: ¬ (p.notionalUsd ≤ 0)   ← what we need
          --   4: p.notionalUsd ≤ allowed (4th split's THEN condition)
          rename_i _ _ hneg _
          exact le_of_lt (lt_of_not_ge hneg)
        · cases h'

/-- Gate 2 resize is always non-negative: the Resize branch is only
    reached past the `calculatePositionSize ≤ 0` rejection, so the
    resize value (which equals ``calculatePositionSize``) is strictly
    positive and in particular non-negative. Needed by the
    certificate-level composition to discharge the non-negativity
    premise of ``checkPortfolio_resize_at_most_nonneg_proposal``. -/
theorem checkConstraints_resize_nonneg
    (p : TradeProposal) (c : AccountConstraints) (n : Rat)
    (h : checkConstraints p c = .Resize n) :
    0 ≤ n := by
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
        · -- In the Resize branch. Anonymous hypotheses (oldest first):
          --   1: ¬ (maxLeverage ≤ 0)
          --   2: ¬ (calculatePositionSize ≤ 0)     ← used
          --   3: ¬ (p.notionalUsd ≤ 0)
          --   4: ¬ (p.notionalUsd ≤ calculatePositionSize)
          injection h' with hn
          rename_i _ hcps _ _
          rw [← hn]
          exact le_of_lt (lt_of_not_ge hcps)

/-- Gate 2 resize is also bounded above by the **submitted proposal**:
    Gate 2 only reaches its `.Resize` branch in the else-case of
    `p.notionalUsd ≤ allowed`, so the resize value (which equals
    `allowed`) is strictly below `p.notionalUsd` and therefore at most
    `p.notionalUsd`. Companion to `_resize_respects_ceiling`: together
    they witness that Gate 2 never inflates the caller's request. -/
theorem checkConstraints_resize_at_most_proposal
    (p : TradeProposal) (c : AccountConstraints) (n : Rat)
    (h : checkConstraints p c = .Resize n) :
    n ≤ p.notionalUsd := by
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
        · -- In this branch: ¬ (p.notionalUsd ≤ allowed), so allowed < p.notionalUsd.
          injection h' with hn
          rename_i hnle
          -- hnle : ¬ (p.notionalUsd ≤ calculatePositionSize ...)
          -- hn   : calculatePositionSize ... = n
          rw [← hn]
          exact le_of_lt (lt_of_not_ge hnle)


-- ── Bayesian Gate 2 (v0.4 Slice 3) ────────────────────────────────
--
-- Parallel to `checkConstraints` but reads its reliability /
-- sample-size inputs from a `BetaPosterior` rather than from
-- `AccountConstraints.(reliability, sampleSize)`. Exact structural
-- twin of the frequentist dispatch; only the sizer call and the
-- caller-supplied inputs change.
--
-- This slice is additive only. `checkConstraints` stays the Gate 2
-- entry point; certificate composition still routes through it.
-- A follow-on slice replaces AccountConstraints's frequentist
-- fields with posterior inputs and re-derives the composition
-- theorems against this function.

open Veritas.Finance Veritas.Learning

/-- Gate 2 dispatch over a Bayesian posterior. Same four-way
    reject / approve / resize structure as `checkConstraints`, but
    the reliability ceiling comes from
    `calculatePositionSizeFromPosterior`. -/
def checkConstraintsBayesian
    (p : TradeProposal) (equity : Rat) (b : BetaPosterior)
    (maxLev : Rat) : Verdict :=
  let allowed := calculatePositionSizeFromPosterior equity b
  if maxLev ≤ 0 then
    .Reject ["leverage_cap_non_positive"]
  else if allowed ≤ 0 then
    .Reject ["no_edge_reliability_below_threshold"]
  else if p.notionalUsd ≤ 0 then
    .Reject ["proposal_notional_non_positive"]
  else if p.notionalUsd ≤ allowed then
    .Approve
  else
    .Resize allowed

theorem checkConstraintsBayesian_approve_within_ceiling
    (p : TradeProposal) (equity : Rat) (b : BetaPosterior) (maxLev : Rat)
    (h : checkConstraintsBayesian p equity b maxLev = .Approve) :
    p.notionalUsd ≤ calculatePositionSizeFromPosterior equity b := by
  have h' :
      (if maxLev ≤ 0 then
        Verdict.Reject ["leverage_cap_non_positive"]
       else if calculatePositionSizeFromPosterior equity b ≤ 0 then
        Verdict.Reject ["no_edge_reliability_below_threshold"]
       else if p.notionalUsd ≤ 0 then
        Verdict.Reject ["proposal_notional_non_positive"]
       else if p.notionalUsd ≤ calculatePositionSizeFromPosterior equity b then
        Verdict.Approve
       else .Resize (calculatePositionSizeFromPosterior equity b))
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

theorem checkConstraintsBayesian_resize_respects_ceiling
    (p : TradeProposal) (equity : Rat) (b : BetaPosterior) (maxLev : Rat)
    (n : Rat)
    (h : checkConstraintsBayesian p equity b maxLev = .Resize n) :
    n ≤ calculatePositionSizeFromPosterior equity b := by
  have h' :
      (if maxLev ≤ 0 then
        Verdict.Reject ["leverage_cap_non_positive"]
       else if calculatePositionSizeFromPosterior equity b ≤ 0 then
        Verdict.Reject ["no_edge_reliability_below_threshold"]
       else if p.notionalUsd ≤ 0 then
        Verdict.Reject ["proposal_notional_non_positive"]
       else if p.notionalUsd ≤ calculatePositionSizeFromPosterior equity b then
        Verdict.Approve
       else .Resize (calculatePositionSizeFromPosterior equity b))
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
