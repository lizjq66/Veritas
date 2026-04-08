/-
  Veritas.Finance.PositionSizing — The core sizer.

  Position size is a pure function of equity and reliability.
  Zero if reliability ≤ 0.5 (no edge), fractional Kelly otherwise,
  hard-capped at 25% of equity.

  Four theorems proved, zero sorry. Proofs depend on Float axioms
  in FloatAxioms.lean — see that file's doc comment for details.
-/
import Veritas.Finance.Kelly

namespace Veritas.Finance

/-- Calculate position size as a dollar amount.
    - Zero when reliability ≤ 0.5 (no perceived edge)
    - Half-Kelly scaled by (reliability − 0.5) otherwise
    - Hard cap at 25% of equity -/
def calculatePositionSize (equity reliability : Float) : Float :=
  if reliability ≤ 0.5 then 0
  else
    let kellyFrac := kellyFraction reliability 1.0
    let halfKelly := kellyFrac * 0.5
    let rawSize := equity * halfKelly
    let cap := equity * 0.25
    if rawSize > cap then cap else rawSize

-- ── Theorems ─────────────────────────────────────────────────────────

theorem positionSize_nonneg (equity reliability : Float)
    (h1 : equity ≥ 0) (_h2 : 0 ≤ reliability) (_h3 : reliability ≤ 1) :
    calculatePositionSize equity reliability ≥ 0 := by
  unfold calculatePositionSize
  split
  · exact Float.le_refl 0
  · dsimp only
    have hk : kellyFraction reliability 1.0 ≥ 0 := kellyFraction_nonneg reliability 1.0
    have h05 : (0 : Float) ≤ 0.5 := by native_decide
    have h025 : (0 : Float) ≤ 0.25 := by native_decide
    have hhk : kellyFraction reliability 1.0 * 0.5 ≥ 0 := Float.mul_nonneg hk h05
    have hraw : equity * (kellyFraction reliability 1.0 * 0.5) ≥ 0 := Float.mul_nonneg h1 hhk
    have hcap : equity * 0.25 ≥ 0 := Float.mul_nonneg h1 h025
    split
    · exact hcap
    · exact hraw

theorem positionSize_capped (equity reliability : Float)
    (h1 : equity ≥ 0) (_h2 : 0 ≤ reliability) (_h3 : reliability ≤ 1) :
    calculatePositionSize equity reliability ≤ equity * 0.25 := by
  unfold calculatePositionSize
  split
  · have h025 : (0 : Float) ≤ 0.25 := by native_decide
    exact Float.mul_nonneg h1 h025
  · dsimp only
    split
    · exact Float.le_refl (equity * 0.25)
    · rename_i _ hgt
      exact Float.le_of_not_gt hgt

theorem positionSize_monotone_in_reliability (equity r1 r2 : Float)
    (h1 : equity ≥ 0) (h2 : r1 ≤ r2) (h3 : 0 ≤ r1) (h4 : r2 ≤ 1) :
    calculatePositionSize equity r1 ≤ calculatePositionSize equity r2 := by
  unfold calculatePositionSize
  split
  · split
    · exact Float.le_refl 0
    · dsimp only
      have hk : kellyFraction r2 1.0 ≥ 0 := kellyFraction_nonneg r2 1.0
      have h05 : (0 : Float) ≤ 0.5 := by native_decide
      have h025 : (0 : Float) ≤ 0.25 := by native_decide
      have hhk : kellyFraction r2 1.0 * 0.5 ≥ 0 := Float.mul_nonneg hk h05
      have hraw : equity * (kellyFraction r2 1.0 * 0.5) ≥ 0 := Float.mul_nonneg h1 hhk
      have hcap : equity * 0.25 ≥ 0 := Float.mul_nonneg h1 h025
      split <;> assumption
  · rename_i hr1
    split
    · exact absurd (Float.le_trans h2 (by assumption)) hr1
    · dsimp only
      have h1g : (1.0 : Float) > (0 : Float) := by native_decide
      have h05 : (0 : Float) ≤ 0.5 := by native_decide
      have hkm : kellyFraction r1 1.0 ≤ kellyFraction r2 1.0 :=
        kellyFraction_mono h2 h3 h4 h1g
      have hkm5 : kellyFraction r1 1.0 * 0.5 ≤ kellyFraction r2 1.0 * 0.5 :=
        Float.mul_le_mul_of_nonneg_right hkm h05
      have hraw_mono : equity * (kellyFraction r1 1.0 * 0.5) ≤
          equity * (kellyFraction r2 1.0 * 0.5) :=
        Float.mul_le_mul_of_nonneg_left hkm5 h1
      split
      · split
        · exact Float.le_refl _
        · rename_i hraw1gt hraw2ngt
          have hraw2le := Float.le_of_not_gt hraw2ngt
          have hraw1_le_cap := Float.le_trans hraw_mono hraw2le
          exact absurd hraw1gt (Float.not_gt_of_le hraw1_le_cap)
      · split
        · exact Float.le_of_not_gt (by assumption)
        · exact hraw_mono

theorem positionSize_zero_at_no_edge (equity reliability : Float)
    (h1 : reliability ≤ 0.5) :
    calculatePositionSize equity reliability = 0 := by
  unfold calculatePositionSize
  rw [if_pos h1]

end Veritas.Finance
