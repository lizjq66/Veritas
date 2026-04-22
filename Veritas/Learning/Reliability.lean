/-
  Veritas.Learning.Reliability — Assumption reliability tracking.

  The learner: after each trade, update the assumption's win/total stats.
  Reliability = wins / total, defaulting to 1/2 when no history exists.

  v0.2 Slice 5: arithmetic is exact `Rat` (via Mathlib). Theorems
  below have zero dependence on Float rounding axioms. The `wins ≤
  total` invariant is enforced at the type level.
-/
import Veritas.Types
import Mathlib.Algebra.Order.Field.Basic
import Mathlib.Data.Rat.Defs
import Mathlib.Tactic.Positivity
import Mathlib.Tactic.Linarith

namespace Veritas.Learning

open Veritas

/-- Historical performance stats for one assumption.
    The `wins_le_total` field enforces the invariant at the type level. -/
structure ReliabilityStats where
  wins : Nat
  total : Nat
  wins_le_total : wins ≤ total

instance : BEq ReliabilityStats where
  beq a b := a.wins == b.wins && a.total == b.total

instance : Inhabited ReliabilityStats where
  default := ⟨0, 0, Nat.le_refl 0⟩

instance : Repr ReliabilityStats where
  reprPrec s _ := s!"ReliabilityStats(wins={s.wins}, total={s.total})"

/-- Smart constructor with runtime validation. -/
def ReliabilityStats.mk? (wins total : Nat) : Option ReliabilityStats :=
  if h : wins ≤ total then some ⟨wins, total, h⟩ else none

/-- Convert an exact `Rat` to a `Float` for JSON / CLI output. -/
def ratToFloat (r : Rat) : Float :=
  Float.ofInt r.num / r.den.toFloat

/-- Step 8: Learn — update stats after a trade closes. -/
def updateReliability (stats : ReliabilityStats) (reason : ExitReason) : ReliabilityStats :=
  match reason with
  | .AssumptionMet   => ⟨stats.wins + 1, stats.total + 1,
                          Nat.add_le_add_right stats.wins_le_total 1⟩
  | .AssumptionBroke  => ⟨stats.wins, stats.total + 1,
                          Nat.le_succ_of_le stats.wins_le_total⟩
  | .StopLoss        => ⟨stats.wins, stats.total + 1,
                          Nat.le_succ_of_le stats.wins_le_total⟩

/-- Compute reliability score from stats, as an exact rational.
    Returns 1/2 when no history exists. -/
def reliabilityScore (stats : ReliabilityStats) : Rat :=
  if stats.total = 0 then (1 : Rat) / 2
  else (stats.wins : Rat) / (stats.total : Rat)

-- ── Theorems (no Float axioms) ───────────────────────────────────────

theorem reliabilityUpdate_monotone_on_wins (stats : ReliabilityStats)
    (h : stats.total > 0) :
    reliabilityScore (updateReliability stats .AssumptionMet)
      ≥ reliabilityScore stats := by
  unfold reliabilityScore updateReliability
  simp only
  have htot : stats.total ≠ 0 := Nat.pos_iff_ne_zero.mp h
  have htot1 : stats.total + 1 ≠ 0 := Nat.succ_ne_zero _
  rw [if_neg htot, if_neg htot1]
  rw [ge_iff_le, div_le_div_iff₀
        (by exact_mod_cast h)
        (by push_cast; linarith [Nat.zero_le stats.total])]
  have hwt : (stats.wins : ℚ) ≤ (stats.total : ℚ) :=
    by exact_mod_cast stats.wins_le_total
  push_cast
  linarith

theorem reliabilityUpdate_bounded (stats : ReliabilityStats) :
    0 ≤ reliabilityScore stats ∧ reliabilityScore stats ≤ 1 := by
  unfold reliabilityScore
  by_cases h : stats.total = 0
  · rw [if_pos h]
    exact ⟨by norm_num, by norm_num⟩
  · rw [if_neg h]
    have hpos : 0 < stats.total := Nat.pos_of_ne_zero h
    refine ⟨?_, ?_⟩
    · positivity
    · rw [div_le_one (by exact_mod_cast hpos)]
      exact_mod_cast stats.wins_le_total

-- ── Multi-assumption reliability aggregation (v0.2 Slice 4 + 5) ──

/-- Aggregate a list of per-assumption reliability records into the
    single (reliability, sampleSize) pair Gate 2 consumes.

    Element-wise minimum:
      aggregate.reliability = min over inputs of each input's score
      aggregate.sampleSize  = min over inputs of each input's total -/
def aggregateReliability : List ReliabilityStats → Rat × Nat
  | []      => ((1 : Rat) / 2, 0)
  | s :: rs =>
    rs.foldl
      (fun (accRel, accSz) x =>
        (min accRel (reliabilityScore x), Nat.min accSz x.total))
      (reliabilityScore s, s.total)

theorem aggregateReliability_empty :
    aggregateReliability [] = ((1 : Rat) / 2, 0) := rfl

theorem aggregateReliability_singleton (s : ReliabilityStats) :
    aggregateReliability [s] = (reliabilityScore s, s.total) := rfl

theorem aggregateReliability_sampleSize_le_head
    (s : ReliabilityStats) (rs : List ReliabilityStats) :
    (aggregateReliability (s :: rs)).2 ≤ s.total := by
  unfold aggregateReliability
  have aux : ∀ (xs : List ReliabilityStats) (initR : Rat) (initSz : Nat),
      (xs.foldl
        (fun (accRel, accSz) x =>
          (min accRel (reliabilityScore x), Nat.min accSz x.total))
        (initR, initSz)).2 ≤ initSz := by
    intro xs
    induction xs with
    | nil => intro _ _; exact Nat.le_refl _
    | cons y ys ih =>
      intro initR initSz
      simp only [List.foldl]
      exact Nat.le_trans (ih _ _) (Nat.min_le_left _ _)
  exact aux rs (reliabilityScore s) s.total

/-- **Strong aggregate theorem** (unlocked by Slice 5's move to exact
    rationals): aggregate reliability is ≤ every input's reliability.
    Justifies calling the aggregation "conservative". -/
theorem aggregateReliability_score_le_each
    (stats : List ReliabilityStats) (s : ReliabilityStats)
    (h : s ∈ stats) :
    (aggregateReliability stats).1 ≤ reliabilityScore s := by
  have aux : ∀ (xs : List ReliabilityStats) (initR : Rat) (initSz : Nat)
      (t : ReliabilityStats),
      t ∈ xs →
      (xs.foldl
        (fun (accRel, accSz) x =>
          (min accRel (reliabilityScore x), Nat.min accSz x.total))
        (initR, initSz)).1 ≤ reliabilityScore t := by
    intro xs
    induction xs with
    | nil => intro _ _ _ hmem; cases hmem
    | cons y ys ih =>
      intro initR initSz t hmem
      simp only [List.foldl]
      cases hmem with
      | head =>
        have monotone : ∀ (zs : List ReliabilityStats) (r : Rat) (sz : Nat),
            (zs.foldl
              (fun (accRel, accSz) x =>
                (min accRel (reliabilityScore x), Nat.min accSz x.total))
              (r, sz)).1 ≤ r := by
          intro zs
          induction zs with
          | nil => intro _ _; exact le_refl _
          | cons z zs ih2 =>
            intro r sz
            simp only [List.foldl]
            exact le_trans (ih2 _ _) (min_le_left _ _)
        have step := monotone ys (min initR (reliabilityScore y))
          (Nat.min initSz y.total)
        exact le_trans step (min_le_right _ _)
      | tail _ htail => exact ih _ _ t htail
  cases stats with
  | nil => cases h
  | cons first ys =>
    unfold aggregateReliability
    have monotone : ∀ (zs : List ReliabilityStats) (r : Rat) (sz : Nat),
        (zs.foldl
          (fun (accRel, accSz) x =>
            (min accRel (reliabilityScore x), Nat.min accSz x.total))
          (r, sz)).1 ≤ r := by
      intro zs
      induction zs with
      | nil => intro _ _; exact le_refl _
      | cons z zs ih2 =>
        intro r sz
        simp only [List.foldl]
        exact le_trans (ih2 _ _) (min_le_left _ _)
    rcases List.mem_cons.mp h with heq | htail
    · rw [heq]
      exact monotone ys (reliabilityScore first) first.total
    · exact aux ys (reliabilityScore first) first.total s htail

end Veritas.Learning
