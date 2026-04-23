/-
  Veritas.Finance.PositionSizing — The core sizer.

  Position size is a pure function of equity, reliability, and sample size.

  Two phases:
    1. Exploration (sampleSize < 10): fixed 1% of equity, regardless of
       reliability. Breaks the cold-start deadlock.
    2. Exploitation (sampleSize ≥ 10): fractional Kelly, zero if
       reliability ≤ 1/2 (no edge), hard-capped at 25% of equity.

  v0.2 Slice 5: migrated to `Rat`. Theorems proved with Mathlib
  lemmas; no Float rounding axioms.
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

/-- Calculate position size as a dollar amount.
    - Exploration phase (sampleSize < 10): equity × 1%
    - Exploitation phase: zero when reliability ≤ 1/2, half-Kelly otherwise
    - Hard cap at 25% of equity in exploitation phase -/
def calculatePositionSize (equity reliability : Rat) (sampleSize : Nat) : Rat :=
  if sampleSize < explorationThreshold then
    equity * explorationFraction
  else if reliability ≤ 1 / 2 then 0
  else
    let kellyFrac := kellyFraction reliability 1
    let halfKelly := kellyFrac * (1 / 2)
    let rawSize := equity * halfKelly
    let cap := equity * exploitationCap
    if rawSize > cap then cap else rawSize

-- ── Theorems (no Float axioms) ───────────────────────────────────────

theorem positionSize_explorationCapped (equity reliability : Rat) (sampleSize : Nat)
    (h : sampleSize < explorationThreshold) :
    calculatePositionSize equity reliability sampleSize =
      equity * explorationFraction := by
  unfold calculatePositionSize
  simp [h]

theorem positionSize_zero_at_no_edge (equity reliability : Rat) (sampleSize : Nat)
    (h1 : reliability ≤ 1 / 2) (h2 : sampleSize ≥ explorationThreshold) :
    calculatePositionSize equity reliability sampleSize = 0 := by
  unfold calculatePositionSize
  rw [if_neg (Nat.not_lt.mpr h2), if_pos h1]

theorem positionSize_nonneg (equity reliability : Rat) (sampleSize : Nat)
    (h1 : equity ≥ 0) (_h2 : 0 ≤ reliability) (_h3 : reliability ≤ 1)
    (h4 : sampleSize ≥ explorationThreshold) :
    calculatePositionSize equity reliability sampleSize ≥ 0 := by
  unfold calculatePositionSize
  simp only [Nat.not_lt.mpr h4, ↓reduceIte]
  split
  · exact le_refl 0
  · split
    · exact mul_nonneg h1 (by unfold exploitationCap; norm_num)
    · exact mul_nonneg h1 (mul_nonneg (kellyFraction_nonneg reliability 1) (by norm_num))

theorem positionSize_capped (equity reliability : Rat) (sampleSize : Nat)
    (h1 : equity ≥ 0) (_h2 : 0 ≤ reliability) (_h3 : reliability ≤ 1)
    (h4 : sampleSize ≥ explorationThreshold) :
    calculatePositionSize equity reliability sampleSize ≤ equity * exploitationCap := by
  unfold calculatePositionSize
  simp only [Nat.not_lt.mpr h4, ↓reduceIte]
  split
  · exact mul_nonneg h1 (by unfold exploitationCap; norm_num)
  · split
    · exact le_refl _
    · rename_i _ hgt
      exact le_of_not_gt hgt

theorem positionSize_monotone_in_reliability (equity r1 r2 : Rat) (sampleSize : Nat)
    (h1 : equity ≥ 0) (h2 : r1 ≤ r2) (h3 : 0 ≤ r1) (h4 : r2 ≤ 1)
    (h5 : sampleSize ≥ explorationThreshold) :
    calculatePositionSize equity r1 sampleSize ≤ calculatePositionSize equity r2 sampleSize := by
  unfold calculatePositionSize
  simp only [Nat.not_lt.mpr h5, ↓reduceIte]
  have hkm := kellyFraction_mono h2 h3 h4 (by norm_num : (1 : Rat) > 0)
  have hkh : kellyFraction r1 1 * (1 / 2) ≤ kellyFraction r2 1 * (1 / 2) :=
    mul_le_mul_of_nonneg_right hkm (by norm_num)
  have hmul : equity * (kellyFraction r1 1 * (1 / 2))
              ≤ equity * (kellyFraction r2 1 * (1 / 2)) :=
    mul_le_mul_of_nonneg_left hkh h1
  split
  · split
    · exact le_refl 0
    · split
      · exact mul_nonneg h1 (by unfold exploitationCap; norm_num)
      · exact mul_nonneg h1
          (mul_nonneg (kellyFraction_nonneg r2 1) (by norm_num))
  · rename_i hr1
    split
    · rename_i hgt
      split
      · rename_i hr2; exact absurd (le_trans h2 hr2) hr1
      · split
        · exact le_refl _
        · exact le_trans (le_of_lt hgt) hmul
    · rename_i hng
      split
      · rename_i hr2; exact absurd (le_trans h2 hr2) hr1
      · split
        · exact le_of_not_gt hng
        · exact hmul


-- ── Bayesian sizing (v0.4 Slice 2) ──────────────────────────────────
--
-- Parallel to `calculatePositionSize` but driven by a Beta posterior
-- instead of a `(reliability, sampleSize)` point estimate. Still
-- separate from Gate 2 in this slice — the integration lands in a
-- follow-on where we can retire the frequentist path in one
-- deliberate step rather than carrying both branches forever.

/-- Bayesian position sizer: same two-phase structure as
    `calculatePositionSize`, but reads its reliability point estimate
    from `BetaPosterior.posteriorMean` and its sample count from
    `successes + failures`. The Beta prior terms keep this behavior
    robust at zero observations (posterior mean = 1/2 under the
    default Beta(1,1)) so Gate 2's cold-start behavior is preserved
    when we wire this in. -/
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

end Veritas.Finance
