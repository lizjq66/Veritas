/-
  Veritas.Finance.Kelly — Kelly criterion as a pure function.

  The Kelly fraction tells you the optimal bet size given a win
  probability and win/loss ratio. We use fractional Kelly (half)
  in PositionSizing for conservatism.
-/
import Veritas.Finance.FloatAxioms

namespace Veritas.Finance

/-- Full Kelly fraction: (b·p − q) / b
    where p = winProb, q = 1 − p, b = winLossRatio.
    Returns 0 if the edge is non-positive. -/
def kellyFraction (winProb winLossRatio : Float) : Float :=
  if winLossRatio ≤ 0.0 then 0.0
  else
    let p := winProb
    let q := 1.0 - p
    let b := winLossRatio
    let f := (b * p - q) / b
    if f ≤ 0.0 then 0.0 else f

-- ── Kelly fraction properties ────────────────────────────────────────

theorem kellyFraction_nonneg (p b : Float) :
    kellyFraction p b ≥ 0 := by
  unfold kellyFraction
  split
  · rw [Float.zero_point_zero_eq]; exact Float.le_refl 0
  · dsimp only; split
    · rw [Float.zero_point_zero_eq]; exact Float.le_refl 0
    · rename_i _ hfle
      rw [← Float.zero_point_zero_eq]; exact Float.not_le_to_ge hfle

theorem kellyFraction_mono {p1 p2 b : Float} :
    p1 ≤ p2 → 0 ≤ p1 → p2 ≤ 1 → b > 0 →
    kellyFraction p1 b ≤ kellyFraction p2 b := by
  intro hp12 _hp1 _hp2 hb
  unfold kellyFraction
  have hbnle : ¬(b ≤ 0.0) := by
    rw [Float.zero_point_zero_eq]; exact Float.not_le_of_gt hb
  simp only [hbnle, ↓reduceIte]
  -- Numerator monotonicity: (b*p1 - (1-p1)) ≤ (b*p2 - (1-p2))
  have hnum : b * p1 - (1.0 - p1) ≤ b * p2 - (1.0 - p2) := by
    have hbp : b * p1 ≤ b * p2 := Float.mul_le_mul_of_nonneg_left hp12 (Float.le_of_gt hb)
    have hq : 1.0 - p2 ≤ 1.0 - p1 := Float.sub_le_sub_left hp12
    exact Float.le_trans (Float.sub_le_sub_right hbp) (Float.sub_le_sub_left hq)
  have hdiv : (b * p1 - (1.0 - p1)) / b ≤ (b * p2 - (1.0 - p2)) / b :=
    Float.div_le_div_of_nonneg_right hnum hb
  -- Four cases from the two inner if-branches
  split <;> split
  · -- Both ≤ 0: 0.0 ≤ 0.0
    exact Float.le_refl _
  · -- f1 ≤ 0, f2 > 0: 0.0 ≤ f2
    rename_i hf1 hf2
    rw [Float.zero_point_zero_eq]
    exact Float.not_le_to_ge (by rw [← Float.zero_point_zero_eq]; exact hf2)
  · -- f1 > 0, f2 ≤ 0: impossible (f1 ≤ f2 ≤ 0 contradicts f1 > 0)
    rename_i hf1 hf2
    exact absurd (Float.le_trans hdiv hf2) hf1
  · -- Both > 0: use division monotonicity
    exact Float.div_le_div_of_nonneg_right hnum hb

end Veritas.Finance
