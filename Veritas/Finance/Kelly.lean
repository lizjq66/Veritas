/-
  Veritas.Finance.Kelly — Kelly criterion as a pure function.

  The Kelly fraction tells you the optimal bet size given a win
  probability and win/loss ratio. We use fractional Kelly (half)
  in PositionSizing for conservatism.

  v0.2 Slice 5: migrated to exact `Rat` arithmetic. Theorems below
  are proved against `Rat` with Mathlib's ordered-field lemmas;
  no dependence on IEEE 754 rounding axioms.
-/
import Mathlib.Algebra.Order.Field.Basic
import Mathlib.Data.Rat.Defs
import Mathlib.Tactic.Positivity
import Mathlib.Tactic.Linarith

namespace Veritas.Finance

/-- Full Kelly fraction: (b·p − q) / b
    where p = winProb, q = 1 − p, b = winLossRatio.
    Returns 0 if the edge is non-positive. -/
def kellyFraction (winProb winLossRatio : Rat) : Rat :=
  if winLossRatio ≤ 0 then 0
  else
    let p := winProb
    let q := 1 - p
    let b := winLossRatio
    let f := (b * p - q) / b
    if f ≤ 0 then 0 else f

-- ── Kelly fraction properties (no Float axioms) ────────────────────

theorem kellyFraction_nonneg (p b : Rat) :
    kellyFraction p b ≥ 0 := by
  unfold kellyFraction
  split
  · exact le_refl 0
  · dsimp only
    split
    · exact le_refl 0
    · rename_i _ hfle
      exact le_of_not_ge hfle

theorem kellyFraction_mono {p1 p2 b : Rat} :
    p1 ≤ p2 → 0 ≤ p1 → p2 ≤ 1 → b > 0 →
    kellyFraction p1 b ≤ kellyFraction p2 b := by
  intro hp12 _hp1 _hp2 hb
  unfold kellyFraction
  have hbnle : ¬(b ≤ 0) := not_le.mpr hb
  simp only [hbnle, ↓reduceIte]
  have hnum : b * p1 - (1 - p1) ≤ b * p2 - (1 - p2) := by
    have hbp : b * p1 ≤ b * p2 :=
      mul_le_mul_of_nonneg_left hp12 (le_of_lt hb)
    linarith
  have hdiv : (b * p1 - (1 - p1)) / b ≤ (b * p2 - (1 - p2)) / b :=
    div_le_div_of_nonneg_right hnum (le_of_lt hb)
  split <;> split
  · exact le_refl _
  · rename_i _ hf2
    exact le_of_lt (lt_of_not_ge hf2)
  · rename_i hf1 hf2
    exact absurd (le_trans hdiv hf2) hf1
  · exact hdiv

end Veritas.Finance
