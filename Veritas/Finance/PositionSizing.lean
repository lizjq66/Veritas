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

end Veritas.Finance
