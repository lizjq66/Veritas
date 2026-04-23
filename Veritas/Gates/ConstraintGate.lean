/-
  Veritas.Gates.ConstraintGate — Gate 2: strategy-constraint compatibility.

  Given a proposed trade and the caller's account constraints, decide
  whether the trade is allowed at its requested size. The verifier may:
    - APPROVE the trade unchanged
    - RESIZE it downward to fit within the reliability-adjusted ceiling
    - REJECT it if no non-zero size is permissible

  Gate 2's formal property: any value it approves or resizes to is
  bounded by `calculatePositionSizeFromPosterior`, which carries its
  own theorems in `Veritas.Finance.PositionSizing`.

  v0.4: the reliability input is a `BetaPosterior` derived from the
  account's observed `(successes, failures)` and its Beta prior
  (defaults: uniform Laplace prior). The previous frequentist
  `(reliability, sampleSize)` input has been retired; see
  `docs/migration-plan-2026-04-23.md` for the migration rationale.

  Gate 2 does not know about portfolio state. That belongs to Gate 3.
-/
import Veritas.Gates.Types
import Veritas.Finance.PositionSizing

namespace Veritas.Gates

open Veritas Veritas.Finance Veritas.Learning

/-- Gate 2: check that the proposed notional fits within the account's
    posterior-driven reliability ceiling. -/
def checkConstraints (p : TradeProposal) (c : AccountConstraints) : Verdict :=
  let allowed := calculatePositionSizeFromPosterior c.equity c.posterior
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
    p.notionalUsd ≤ calculatePositionSizeFromPosterior c.equity c.posterior := by
  have h' :
      (if c.maxLeverage ≤ 0 then
        Verdict.Reject ["leverage_cap_non_positive"]
       else if calculatePositionSizeFromPosterior c.equity c.posterior ≤ 0 then
        Verdict.Reject ["no_edge_reliability_below_threshold"]
       else if p.notionalUsd ≤ 0 then
        Verdict.Reject ["proposal_notional_non_positive"]
       else if p.notionalUsd ≤ calculatePositionSizeFromPosterior c.equity c.posterior then
        Verdict.Approve
       else .Resize (calculatePositionSizeFromPosterior c.equity c.posterior))
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
    n ≤ calculatePositionSizeFromPosterior c.equity c.posterior := by
  have h' :
      (if c.maxLeverage ≤ 0 then
        Verdict.Reject ["leverage_cap_non_positive"]
       else if calculatePositionSizeFromPosterior c.equity c.posterior ≤ 0 then
        Verdict.Reject ["no_edge_reliability_below_threshold"]
       else if p.notionalUsd ≤ 0 then
        Verdict.Reject ["proposal_notional_non_positive"]
       else if p.notionalUsd ≤ calculatePositionSizeFromPosterior c.equity c.posterior then
        Verdict.Approve
       else .Resize (calculatePositionSizeFromPosterior c.equity c.posterior))
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
       else if calculatePositionSizeFromPosterior c.equity c.posterior ≤ 0 then
        Verdict.Reject ["no_edge_reliability_below_threshold"]
       else if p.notionalUsd ≤ 0 then
        Verdict.Reject ["proposal_notional_non_positive"]
       else if p.notionalUsd ≤ calculatePositionSizeFromPosterior c.equity c.posterior then
        Verdict.Approve
       else .Resize (calculatePositionSizeFromPosterior c.equity c.posterior))
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
          --   2: ¬ (calculatePositionSizeFromPosterior ≤ 0)
          --   3: ¬ (p.notionalUsd ≤ 0)   ← what we need
          --   4: p.notionalUsd ≤ allowed (4th split's THEN condition)
          rename_i _ _ hneg _
          exact le_of_lt (lt_of_not_ge hneg)
        · cases h'

/-- Gate 2 resize is always non-negative: the Resize branch is only
    reached past the sizer-≤-0 rejection, so the resize value (which
    equals the posterior-driven ceiling) is strictly positive. Needed
    by the certificate-level composition to discharge the
    non-negativity premise of
    `checkPortfolio_resize_at_most_nonneg_proposal`. -/
theorem checkConstraints_resize_nonneg
    (p : TradeProposal) (c : AccountConstraints) (n : Rat)
    (h : checkConstraints p c = .Resize n) :
    0 ≤ n := by
  have h' :
      (if c.maxLeverage ≤ 0 then
        Verdict.Reject ["leverage_cap_non_positive"]
       else if calculatePositionSizeFromPosterior c.equity c.posterior ≤ 0 then
        Verdict.Reject ["no_edge_reliability_below_threshold"]
       else if p.notionalUsd ≤ 0 then
        Verdict.Reject ["proposal_notional_non_positive"]
       else if p.notionalUsd ≤ calculatePositionSizeFromPosterior c.equity c.posterior then
        Verdict.Approve
       else .Resize (calculatePositionSizeFromPosterior c.equity c.posterior))
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
          --   2: ¬ (calculatePositionSizeFromPosterior ≤ 0)  ← used
          --   3: ¬ (p.notionalUsd ≤ 0)
          --   4: ¬ (p.notionalUsd ≤ calculatePositionSizeFromPosterior)
          injection h' with hn
          rename_i _ hcps _ _
          rw [← hn]
          exact le_of_lt (lt_of_not_ge hcps)

/-- Gate 2 resize is also bounded above by the **submitted proposal**:
    Gate 2 only reaches its `.Resize` branch in the else-case of
    `p.notionalUsd ≤ allowed`, so the resize value (which equals the
    posterior-driven ceiling) is strictly below `p.notionalUsd` and
    therefore at most `p.notionalUsd`. Companion to
    `_resize_respects_ceiling`: together they witness that Gate 2
    never inflates the caller's request. -/
theorem checkConstraints_resize_at_most_proposal
    (p : TradeProposal) (c : AccountConstraints) (n : Rat)
    (h : checkConstraints p c = .Resize n) :
    n ≤ p.notionalUsd := by
  have h' :
      (if c.maxLeverage ≤ 0 then
        Verdict.Reject ["leverage_cap_non_positive"]
       else if calculatePositionSizeFromPosterior c.equity c.posterior ≤ 0 then
        Verdict.Reject ["no_edge_reliability_below_threshold"]
       else if p.notionalUsd ≤ 0 then
        Verdict.Reject ["proposal_notional_non_positive"]
       else if p.notionalUsd ≤ calculatePositionSizeFromPosterior c.equity c.posterior then
        Verdict.Approve
       else .Resize (calculatePositionSizeFromPosterior c.equity c.posterior))
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
          rw [← hn]
          exact le_of_lt (lt_of_not_ge hnle)

end Veritas.Gates
