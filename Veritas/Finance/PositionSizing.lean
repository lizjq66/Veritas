/-
  Veritas.Finance.PositionSizing — The core sizer.

  Position size is a pure function of equity, reliability, and sample size.

  Two phases:
    1. Exploration (sampleSize < 10): fixed 1% of equity, regardless of
       reliability. This breaks the cold-start deadlock where zero trades
       means zero data means zero reliability means zero position.
    2. Exploitation (sampleSize ≥ 10): fractional Kelly, zero if
       reliability ≤ 0.5 (no edge), hard-capped at 25% of equity.

  The exploration/exploitation split is a first-class concept in Lean,
  not a Python workaround. Theorem positionSize_explorationCapped
  formalizes the exploration guarantee.
-/
import Veritas.Finance.Kelly

namespace Veritas.Finance

/-- Number of trades before switching from exploration to exploitation. -/
def explorationThreshold : Nat := 10

/-- Fixed position fraction during exploration (1% of equity). -/
def explorationFraction : Float := 0.01

/-- Calculate position size as a dollar amount.
    - Exploration phase (sampleSize < 10): equity × 1%, always
    - Exploitation phase: zero when reliability ≤ 0.5, half-Kelly otherwise
    - Hard cap at 25% of equity in exploitation phase -/
def calculatePositionSize (equity reliability : Float) (sampleSize : Nat) : Float :=
  if sampleSize < explorationThreshold then
    equity * explorationFraction
  else if reliability ≤ 0.5 then 0
  else
    let kellyFrac := kellyFraction reliability 1.0
    let halfKelly := kellyFrac * 0.5
    let rawSize := equity * halfKelly
    let cap := equity * 0.25
    if rawSize > cap then cap else rawSize

-- ── Theorems ─────────────────────────────────────────────────────────

/-- During exploration, position is fixed at explorationFraction of equity. -/
theorem positionSize_explorationCapped (equity reliability : Float) (sampleSize : Nat)
    (h : sampleSize < explorationThreshold) :
    calculatePositionSize equity reliability sampleSize =
      equity * explorationFraction := by
  unfold calculatePositionSize
  simp [h]

/-- Post-exploration: zero position when reliability ≤ 0.5 (no edge). -/
theorem positionSize_zero_at_no_edge (equity reliability : Float) (sampleSize : Nat)
    (h1 : reliability ≤ 0.5) (h2 : sampleSize ≥ explorationThreshold) :
    calculatePositionSize equity reliability sampleSize = 0 := by
  unfold calculatePositionSize
  rw [if_neg (Nat.not_lt.mpr h2), if_pos h1]

/-- Post-exploration: position is always non-negative. -/
theorem positionSize_nonneg (equity reliability : Float) (sampleSize : Nat)
    (h1 : equity ≥ 0) (_h2 : 0 ≤ reliability) (_h3 : reliability ≤ 1)
    (h4 : sampleSize ≥ explorationThreshold) :
    calculatePositionSize equity reliability sampleSize ≥ 0 := by sorry

/-- Post-exploration: position never exceeds 25% of equity. -/
theorem positionSize_capped (equity reliability : Float) (sampleSize : Nat)
    (h1 : equity ≥ 0) (_h2 : 0 ≤ reliability) (_h3 : reliability ≤ 1)
    (h4 : sampleSize ≥ explorationThreshold) :
    calculatePositionSize equity reliability sampleSize ≤ equity * 0.25 := by sorry

/-- Post-exploration: reliability monotonically increases position size. -/
theorem positionSize_monotone_in_reliability (equity r1 r2 : Float) (sampleSize : Nat)
    (h1 : equity ≥ 0) (h2 : r1 ≤ r2) (h3 : 0 ≤ r1) (h4 : r2 ≤ 1)
    (h5 : sampleSize ≥ explorationThreshold) :
    calculatePositionSize equity r1 sampleSize ≤ calculatePositionSize equity r2 sampleSize := by sorry

end Veritas.Finance
