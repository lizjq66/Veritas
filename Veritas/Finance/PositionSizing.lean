/-
  Veritas.Finance.PositionSizing — The core sizer.

  Position size is a pure function of equity and a Bayesian posterior
  over the backing assumption's win rate.

  Two phases:
    1. Exploration (successes + failures < 10): fixed 1% of equity,
       regardless of posterior mean. Breaks the cold-start deadlock.
    2. Exploitation (successes + failures ≥ 10): fractional Kelly,
       zero if posterior mean ≤ 1/2 (no edge), hard-capped at 25%
       of equity.

  v0.2 Slice 5: migrated to `Rat`. Theorems proved with Mathlib
  lemmas; no Float rounding axioms.

  v0.4 Slice 4: the frequentist `calculatePositionSize (equity,
  reliability, sampleSize)` and its five theorems have been retired.
  The Bayesian `calculatePositionSizeFromPosterior` (v0.4 Slice 2)
  is now the sole sizer. See `docs/migration-plan-2026-04-23.md`.
-/
import Veritas.Finance.Kelly
import Veritas.Learning.Reliability
import Mathlib.Algebra.Order.Field.Basic
import Mathlib.Tactic.Positivity
import Mathlib.Tactic.Linarith

namespace Veritas.Finance

open Veritas.Learning

/-- Number of trades before switching from exploration to exploitation. -/
def explorationThreshold : Nat := 10

/-- Fixed position fraction during exploration (1% of equity). -/
abbrev explorationFraction : Rat := 1 / 100

/-- Hard cap as fraction of equity during exploitation (25%). -/
abbrev exploitationCap : Rat := 1 / 4

-- ── Bayesian sizer (v0.4 Slice 2, now the sole sizer) ──────────────

/-- Bayesian position sizer: same two-phase structure as the retired
    `calculatePositionSize`, but reads its reliability point estimate
    from `BetaPosterior.posteriorMean` and its sample count from
    `successes + failures`. The Beta prior terms keep this behavior
    robust at zero observations (posterior mean = 1/2 under the
    default Beta(1,1)), so Gate 2's cold-start behavior matches the
    v0.3 frequentist fallback exactly. -/
def calculatePositionSizeFromPosterior
    (equity : Rat) (b : BetaPosterior) : Rat :=
  if b.successes + b.failures < explorationThreshold then
    equity * explorationFraction
  else if b.posteriorMean ≤ 1 / 2 then 0
  else
    let kellyFrac := kellyFraction b.posteriorMean 1
    let halfKelly := kellyFrac * (1 / 2)
    let rawSize := equity * halfKelly
    let cap := equity * exploitationCap
    if rawSize > cap then cap else rawSize

theorem positionSize_fromPosterior_nonneg
    (equity : Rat) (b : BetaPosterior)
    (hEq : equity ≥ 0)
    (hα : 0 ≤ b.priorAlpha) (hβ : 0 ≤ b.priorBeta)
    (hpos : 0 < b.priorAlpha + b.priorBeta)
    (hthr : b.successes + b.failures ≥ explorationThreshold) :
    calculatePositionSizeFromPosterior equity b ≥ 0 := by
  unfold calculatePositionSizeFromPosterior
  simp only [Nat.not_lt.mpr hthr, ↓reduceIte]
  have _hmean := BetaPosterior.posteriorMean_bounded b hα hβ hpos
  split
  · exact le_refl 0
  · split
    · exact mul_nonneg hEq (by unfold exploitationCap; norm_num)
    · exact mul_nonneg hEq
        (mul_nonneg (kellyFraction_nonneg b.posteriorMean 1) (by norm_num))

theorem positionSize_fromPosterior_capped
    (equity : Rat) (b : BetaPosterior)
    (hEq : equity ≥ 0)
    (hα : 0 ≤ b.priorAlpha) (hβ : 0 ≤ b.priorBeta)
    (hpos : 0 < b.priorAlpha + b.priorBeta)
    (hthr : b.successes + b.failures ≥ explorationThreshold) :
    calculatePositionSizeFromPosterior equity b ≤ equity * exploitationCap := by
  unfold calculatePositionSizeFromPosterior
  simp only [Nat.not_lt.mpr hthr, ↓reduceIte]
  have _hmean := BetaPosterior.posteriorMean_bounded b hα hβ hpos
  split
  · exact mul_nonneg hEq (by unfold exploitationCap; norm_num)
  · split
    · exact le_refl _
    · rename_i _ hgt
      exact le_of_not_gt hgt

theorem positionSize_fromPosterior_zero_at_no_edge
    (equity : Rat) (b : BetaPosterior)
    (h1 : b.posteriorMean ≤ 1 / 2)
    (hthr : b.successes + b.failures ≥ explorationThreshold) :
    calculatePositionSizeFromPosterior equity b = 0 := by
  unfold calculatePositionSizeFromPosterior
  rw [if_neg (Nat.not_lt.mpr hthr), if_pos h1]

/-- **Monotonicity in evidence.** Replacing a `BetaPosterior` with
    one that has strictly more observed successes (same failures,
    same priors) never decreases the sizer's output. The Bayesian
    analog of the retired `positionSize_monotone_in_reliability`:
    more evidence in favor of the assumption never reduces Gate 2's
    ceiling.

    The monotonicity is with respect to the posterior-mean input to
    the Kelly fraction, which `posteriorMean_monotone_in_successes`
    already guarantees. -/
theorem positionSize_fromPosterior_monotone_in_successes
    (equity : Rat) (b : BetaPosterior) (k : Nat)
    (hEq : equity ≥ 0)
    (hα : 0 ≤ b.priorAlpha) (hβ : 0 ≤ b.priorBeta)
    (hpos : 0 < b.priorAlpha + b.priorBeta)
    (hthr : b.successes + b.failures ≥ explorationThreshold) :
    calculatePositionSizeFromPosterior equity b
      ≤ calculatePositionSizeFromPosterior equity
          { b with successes := b.successes + k } := by
  unfold calculatePositionSizeFromPosterior
  -- The struct-updated BetaPosterior has `successes + k + failures`
  -- observations, which is still ≥ threshold.
  have hthr' : { b with successes := b.successes + k }.successes
                  + { b with successes := b.successes + k }.failures
                ≥ explorationThreshold := by
    dsimp only
    exact Nat.le_trans hthr (by omega)
  simp only [Nat.not_lt.mpr hthr, Nat.not_lt.mpr hthr', ↓reduceIte]
  -- Posterior mean monotonicity.
  have hmono :=
    BetaPosterior.posteriorMean_monotone_in_successes b k hβ hpos
  -- Split on whether the original posterior is above or below the
  -- edge threshold; the updated one is at least as high.
  by_cases hedge : b.posteriorMean ≤ 1 / 2
  · -- Original posterior at/below edge → sizer = 0; anything the
    -- updated sizer returns is ≥ 0 by `_fromPosterior_nonneg`.
    rw [if_pos hedge]
    by_cases hedge' :
        ({ b with successes := b.successes + k } : BetaPosterior).posteriorMean
          ≤ 1 / 2
    · rw [if_pos hedge']
    · rw [if_neg hedge']
      push_neg at hedge'
      split
      · exact mul_nonneg hEq (by unfold exploitationCap; norm_num)
      · exact mul_nonneg hEq
          (mul_nonneg
            (kellyFraction_nonneg
              ({ b with successes := b.successes + k } : BetaPosterior).posteriorMean 1)
            (by norm_num))
  · -- Original posterior above edge. The updated one is also above
    -- edge (posterior mean only grows).
    push_neg at hedge
    have hedge' :
        ¬ ({ b with successes := b.successes + k } : BetaPosterior).posteriorMean
            ≤ 1 / 2 := by
      push_neg
      exact lt_of_lt_of_le hedge hmono
    rw [if_neg (not_le.mpr hedge), if_neg hedge']
    -- Both branches now use the same `if rawSize > cap then cap else rawSize`
    -- shape. Monotonicity of kellyFraction in its first argument gives
    -- us the comparison on `rawSize`; the outer min-with-cap preserves it.
    have hmeanB_nn :
        0 ≤ ({ b with successes := b.successes + k } : BetaPosterior).posteriorMean := by
      exact le_of_lt (lt_trans (by norm_num : (0 : Rat) < 1 / 2)
                               (lt_of_lt_of_le hedge hmono))
    have hkmono :
        kellyFraction b.posteriorMean 1
          ≤ kellyFraction
              ({ b with successes := b.successes + k } : BetaPosterior).posteriorMean
              1 := by
      -- kellyFraction_mono wants `p₁ ≤ p₂ ∧ 0 ≤ p₁ ∧ p₂ ≤ 1 ∧ 0 < b`.
      -- We need `posteriorMean ≤ 1` for b-plus-k; that's the
      -- `.posteriorMean_bounded` conjunction's second leg.
      have hbnd := BetaPosterior.posteriorMean_bounded
                      { b with successes := b.successes + k }
                      (by dsimp only; exact hα)
                      hβ (by dsimp only; exact hpos)
      refine kellyFraction_mono hmono ?_ hbnd.2 (by norm_num : (1 : Rat) > 0)
      exact le_of_lt (lt_trans (by norm_num : (0 : Rat) < 1 / 2) hedge)
    have hhkmono :
        kellyFraction b.posteriorMean 1 * (1 / 2)
          ≤ kellyFraction
              ({ b with successes := b.successes + k } : BetaPosterior).posteriorMean
              1 * (1 / 2) :=
      mul_le_mul_of_nonneg_right hkmono (by norm_num)
    have hrawMono :
        equity * (kellyFraction b.posteriorMean 1 * (1 / 2))
          ≤ equity * (kellyFraction
              ({ b with successes := b.successes + k } : BetaPosterior).posteriorMean
              1 * (1 / 2)) :=
      mul_le_mul_of_nonneg_left hhkmono hEq
    have hcapNN : 0 ≤ equity * exploitationCap :=
      mul_nonneg hEq (by unfold exploitationCap; norm_num)
    -- Four-way case split on the two `if rawSize > cap` branches.
    split
    · split
      · exact le_refl _
      · rename_i hgtL hngtR
        -- Left branch: rawL > cap; result = cap. Right branch: rawR ≤ cap;
        -- result = rawR. We need cap ≤ rawR.
        -- But hrawMono: rawL ≤ rawR, and hgtL: rawL > cap, so rawR > cap.
        -- That contradicts `¬ (rawR > cap)`, i.e. rawR ≤ cap, which
        -- with rawR > cap gives equality — cap = rawR. So cap ≤ rawR.
        exact le_of_not_gt (fun hgtR => hngtR (lt_of_lt_of_le hgtL hrawMono))
    · split
      · rename_i hngtL _
        -- Left branch: rawL ≤ cap, result = rawL. Right branch: rawR > cap, result = cap.
        -- Need rawL ≤ cap. That's `hngtL` negated.
        exact le_of_not_gt hngtL
      · exact hrawMono


-- ── Confidence-bound-aware sizing (v0.4 Slice 6) ────────────────────
--
-- Small-sample uncertainty: under the Bayesian sizer introduced in
-- Slice 2, a `BetaPosterior` with `successes = 3, failures = 1`
-- already has posterior mean ≈ 0.67 — well past the 0.5 no-edge
-- cutoff, pushing Gate 2 into an exploitation-phase size even though
-- four observations is nowhere near a reliable evidence base.
--
-- `calculatePositionSizeFromPosterior_pessimistic` wraps the Bayesian
-- sizer with a failure-shift (see `BetaPosterior.pessimisticMean`):
-- the caller passes a `pessimism : Nat` parameter — the number of
-- hypothetical additional losses to simulate — and the sizer uses
-- the pessimistic mean in place of the raw posterior mean. Larger
-- pessimism → smaller sizing; the effect vanishes as the real
-- sample size grows.
--
-- This is Veritas's pragmatic "confidence-bound" aware primitive:
-- a true Beta-quantile lower bound requires the inverse-Beta-CDF
-- which breaks Rat purity; the failure-shift is a legitimate
-- Bayesian operation (equivalent to adopting a more skeptical
-- Beta(α, β + k) prior) that preserves exact rational arithmetic
-- while delivering the "small samples get smaller sizing"
-- behavior.
--
-- Not yet wired into Gate 2. A follow-on slice can thread the
-- pessimism parameter through `AccountConstraints` when there's
-- evidence a caller wants it.

/-- Conservative variant of `calculatePositionSizeFromPosterior`:
    applies a `pessimism`-count failure shift to the supplied
    posterior before sizing. At `pessimism = 0` this is identical
    to the base sizer. -/
def calculatePositionSizeFromPosterior_pessimistic
    (equity : Rat) (b : BetaPosterior) (pessimism : Nat) : Rat :=
  calculatePositionSizeFromPosterior equity
    { b with failures := b.failures + pessimism }

/-- Non-negativity of the conservative sizer, inherited from the
    base sizer applied to the failure-shifted posterior. -/
theorem positionSize_pessimistic_nonneg
    (equity : Rat) (b : BetaPosterior) (pessimism : Nat)
    (hEq : equity ≥ 0)
    (hα : 0 ≤ b.priorAlpha) (hβ : 0 ≤ b.priorBeta)
    (hpos : 0 < b.priorAlpha + b.priorBeta)
    (hthr : b.successes + b.failures ≥ explorationThreshold) :
    calculatePositionSizeFromPosterior_pessimistic equity b pessimism ≥ 0 := by
  -- Translate the hypotheses to the failure-shifted BetaPosterior;
  -- its priors and success-count coincide with `b` definitionally.
  have hthr' : ({b with failures := b.failures + pessimism} : BetaPosterior).successes
                    + ({b with failures := b.failures + pessimism} : BetaPosterior).failures
                  ≥ explorationThreshold := by dsimp only; omega
  exact positionSize_fromPosterior_nonneg equity
      {b with failures := b.failures + pessimism} hEq hα hβ hpos hthr'

/-- 25%-of-equity cap for the conservative sizer. -/
theorem positionSize_pessimistic_capped
    (equity : Rat) (b : BetaPosterior) (pessimism : Nat)
    (hEq : equity ≥ 0)
    (hα : 0 ≤ b.priorAlpha) (hβ : 0 ≤ b.priorBeta)
    (hpos : 0 < b.priorAlpha + b.priorBeta)
    (hthr : b.successes + b.failures ≥ explorationThreshold) :
    calculatePositionSizeFromPosterior_pessimistic equity b pessimism
      ≤ equity * exploitationCap := by
  have hthr' : ({b with failures := b.failures + pessimism} : BetaPosterior).successes
                    + ({b with failures := b.failures + pessimism} : BetaPosterior).failures
                  ≥ explorationThreshold := by dsimp only; omega
  exact positionSize_fromPosterior_capped equity
      {b with failures := b.failures + pessimism} hEq hα hβ hpos hthr'

/-- **Sizing never exceeds the base sizer.** The headline theorem of
    confidence-bound-aware sizing: conservative sizing is always at
    most the raw-posterior sizing, so a caller that turns on
    pessimism never silently *grows* their Gate 2 ceiling. -/
theorem positionSize_pessimistic_le_base
    (equity : Rat) (b : BetaPosterior) (pessimism : Nat)
    (hEq : equity ≥ 0)
    (hα : 0 ≤ b.priorAlpha) (hβ : 0 ≤ b.priorBeta)
    (hpos : 0 < b.priorAlpha + b.priorBeta)
    (hthr : b.successes + b.failures ≥ explorationThreshold) :
    calculatePositionSizeFromPosterior_pessimistic equity b pessimism
      ≤ calculatePositionSizeFromPosterior equity b := by
  unfold calculatePositionSizeFromPosterior_pessimistic
  -- pessimism amounts to a shift in b.failures, which is monotone in
  -- the sense that fewer failures (i.e. the original `b`) yields a
  -- posterior mean at least as large, and the sizer is monotone in
  -- the posterior mean. The formal path routes through
  -- `BetaPosterior.pessimisticMean_le_posteriorMean` and the
  -- sizer's monotonicity — but instead of wiring those together via
  -- a fresh `positionSize_mono_in_posteriorMean` lemma, we compute
  -- by cases on exploration vs exploitation directly.
  unfold calculatePositionSizeFromPosterior
  -- Both sides share the same `if successes+failures < threshold`
  -- branch (we're past the threshold on the unshifted side, and
  -- shifting adds to failures so it's still past the threshold).
  have hthr' : ({ b with failures := b.failures + pessimism } : BetaPosterior).successes
                  + { b with failures := b.failures + pessimism }.failures
                ≥ explorationThreshold := by dsimp only; omega
  simp only [Nat.not_lt.mpr hthr, Nat.not_lt.mpr hthr', ↓reduceIte]
  have hpMono := BetaPosterior.pessimisticMean_le_posteriorMean b pessimism hα hβ hpos
  -- `pessimisticMean b k` = `{b with failures := ...}.posteriorMean`;
  -- propagate into the edge / sizing comparisons.
  by_cases hEdgeShift : ({ b with failures := b.failures + pessimism } : BetaPosterior).posteriorMean
                          ≤ 1 / 2
  · -- shifted side takes 0 branch; original side ≥ 0.
    rw [if_pos hEdgeShift]
    by_cases hEdgeBase : b.posteriorMean ≤ 1 / 2
    · rw [if_pos hEdgeBase]
    · rw [if_neg hEdgeBase]
      split
      · exact mul_nonneg hEq (by unfold exploitationCap; norm_num)
      · exact mul_nonneg hEq
          (mul_nonneg (kellyFraction_nonneg b.posteriorMean 1) (by norm_num))
  · -- shifted side past the edge → base must be too (since shifted ≤ base).
    push_neg at hEdgeShift
    have hEdgeBase : ¬ b.posteriorMean ≤ 1 / 2 := by
      push_neg
      -- pessimisticMean = {b with failures := ...}.posteriorMean,
      -- and we have hEdgeShift: 1/2 < pessimisticMean ≤ posteriorMean (base)
      have : ({ b with failures := b.failures + pessimism } : BetaPosterior).posteriorMean
              ≤ b.posteriorMean := by
        have h := hpMono
        unfold BetaPosterior.pessimisticMean at h
        exact h
      linarith
    rw [if_neg (not_le.mpr hEdgeShift), if_neg hEdgeBase]
    -- Both sides now enter the exploitation-phase branch.
    -- Kelly is monotone in the posterior-mean argument; both
    -- outer min-with-cap branches preserve the comparison.
    have hmeanBase_nn : 0 ≤ b.posteriorMean :=
      (BetaPosterior.posteriorMean_bounded b hα hβ hpos).1
    have hmeanBase_le_one : b.posteriorMean ≤ 1 :=
      (BetaPosterior.posteriorMean_bounded b hα hβ hpos).2
    have hmeanShift_le_base :
        ({ b with failures := b.failures + pessimism } : BetaPosterior).posteriorMean
          ≤ b.posteriorMean := by
      have h := hpMono
      unfold BetaPosterior.pessimisticMean at h
      exact h
    have hmeanShift_nn :
        0 ≤ ({ b with failures := b.failures + pessimism } : BetaPosterior).posteriorMean := by
      exact le_of_lt (lt_trans (by norm_num : (0 : Rat) < 1 / 2) hEdgeShift)
    have hkMono :
        kellyFraction
            ({ b with failures := b.failures + pessimism } : BetaPosterior).posteriorMean
            1
          ≤ kellyFraction b.posteriorMean 1 :=
      kellyFraction_mono hmeanShift_le_base hmeanShift_nn hmeanBase_le_one
                         (by norm_num : (1 : Rat) > 0)
    have hhkMono :
        kellyFraction
            ({ b with failures := b.failures + pessimism } : BetaPosterior).posteriorMean
            1 * (1 / 2)
          ≤ kellyFraction b.posteriorMean 1 * (1 / 2) :=
      mul_le_mul_of_nonneg_right hkMono (by norm_num)
    have hrawMono :
        equity * (kellyFraction
            ({ b with failures := b.failures + pessimism } : BetaPosterior).posteriorMean
            1 * (1 / 2))
          ≤ equity * (kellyFraction b.posteriorMean 1 * (1 / 2)) :=
      mul_le_mul_of_nonneg_left hhkMono hEq
    split_ifs with hcapS hcapB
    · -- rawShift > cap, rawBase > cap: both take cap.
      exact le_refl _
    · -- rawShift > cap, rawBase ≤ cap: need cap ≤ rawBase. Since
      -- rawShift > cap and rawShift ≤ rawBase, rawBase > cap too —
      -- contradiction with hcapB, so this branch is vacuous.
      exact absurd (lt_of_lt_of_le hcapS hrawMono) hcapB
    · -- rawShift ≤ cap, rawBase > cap: need rawShift ≤ cap.
      exact le_of_not_gt hcapS
    · -- rawShift ≤ cap, rawBase ≤ cap: need rawShift ≤ rawBase.
      exact hrawMono

end Veritas.Finance
