/-
  Veritas.Learning.Reliability — Assumption reliability tracking.

  The learner: after each trade, update the assumption's win/total stats.
  Reliability = wins / total, defaulting to 0.5 when no history exists.

  The wins ≤ total invariant is enforced at the type level.
-/
import Veritas.Types
import Veritas.Finance.FloatAxioms

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

/-- Step 8: Learn — update stats after a trade closes.
    assumption_met   → wins += 1, total += 1
    assumption_broke → total += 1
    stop_loss        → total += 1 -/
def updateReliability (stats : ReliabilityStats) (reason : ExitReason) : ReliabilityStats :=
  match reason with
  | .AssumptionMet   => ⟨stats.wins + 1, stats.total + 1,
                          Nat.add_le_add_right stats.wins_le_total 1⟩
  | .AssumptionBroke  => ⟨stats.wins, stats.total + 1,
                          Nat.le_succ_of_le stats.wins_le_total⟩
  | .StopLoss        => ⟨stats.wins, stats.total + 1,
                          Nat.le_succ_of_le stats.wins_le_total⟩

/-- Compute reliability score from stats. Returns 0.5 when no history. -/
def reliabilityScore (stats : ReliabilityStats) : Float :=
  if stats.total == 0 then 0.5
  else stats.wins.toFloat / stats.total.toFloat

-- ── Theorems ─────────────────────────────────────────────────────────

private theorem beq_false_of_ne {n : Nat} (h : ¬(n == 0) = true) : n > 0 := by
  simp [BEq.beq] at h; omega

open Veritas.Finance in
/-- After a win, reliability never decreases. -/
theorem reliabilityUpdate_monotone_on_wins (stats : ReliabilityStats)
    (h : stats.total > 0) :
    reliabilityScore (updateReliability stats .AssumptionMet)
      ≥ reliabilityScore stats := by
  unfold reliabilityScore updateReliability
  simp only
  split
  · rename_i h1; simp [BEq.beq] at h1
  · split
    · rename_i _ h2; simp [BEq.beq] at h2; omega
    · exact Float.div_succ_mono stats.wins_le_total h

open Veritas.Finance in
/-- Reliability is always in [0, 1]. -/
theorem reliabilityUpdate_bounded (stats : ReliabilityStats) :
    0 ≤ reliabilityScore stats ∧ reliabilityScore stats ≤ 1 := by
  unfold reliabilityScore
  split
  · exact ⟨by native_decide, by native_decide⟩
  · rename_i hne
    have hpos := beq_false_of_ne hne
    exact ⟨Float.div_nonneg (Float.Nat_toFloat_nonneg _) (Float.Nat_toFloat_pos hpos),
           Float.div_le_one (Float.Nat_toFloat_mono stats.wins_le_total) (Float.Nat_toFloat_pos hpos)⟩

-- ── Multi-assumption reliability aggregation (v0.2 Slice 4) ──────

/-- Pick-wise minimum of two floats via `if`. Avoids relying on
    whether `Float.min` is surfaced from the Lean 4 FFI. -/
def floatMin (a b : Float) : Float :=
  if a ≤ b then a else b

/-- Aggregate a list of per-assumption reliability records into the
    single (reliability, sampleSize) pair Gate 2 actually consumes.

    The aggregation is deliberately the most conservative element-wise:

      aggregate.reliability = minimum reliability across the inputs
      aggregate.sampleSize  = minimum sample size across the inputs

    Two kinds of conservatism:
      * min reliability →  Gate 2's ceiling reflects the weakest link.
      * min sample size →  if ANY attached assumption is under-sampled
                           (below `explorationThreshold`), Gate 2 falls
                           back to exploration-fraction sizing; a
                           single untested assumption is enough to
                           force the whole trade into cold-start mode.

    Empty input returns `(0.5, 0)` — the default-no-data pair Gate 2
    sees when no assumption is attached. -/
def aggregateReliability : List ReliabilityStats → Float × Nat
  | []      => (0.5, 0)
  | s :: rs =>
    rs.foldl
      (fun (accRel, accSz) x =>
        (floatMin accRel (reliabilityScore x),
         Nat.min accSz x.total))
      (reliabilityScore s, s.total)

-- ── Aggregation theorems ─────────────────────────────────────────

/-- Aggregating no stats yields the default `(0.5, 0)` pair. -/
theorem aggregateReliability_empty :
    aggregateReliability [] = (0.5, 0) := rfl

/-- Aggregating a single-element list yields that element's own score
    and total. In particular, aggregation is idempotent for callers
    that happen to have exactly one assumption attached. -/
theorem aggregateReliability_singleton (s : ReliabilityStats) :
    aggregateReliability [s] = (reliabilityScore s, s.total) := rfl

/-- The aggregate sample-size never exceeds any input's total — a
    consequence of taking `Nat.min` at each foldl step. This is
    the conservatism property that forces the trade into exploration
    phase whenever any attached assumption is under-sampled. -/
theorem aggregateReliability_sampleSize_le_head
    (s : ReliabilityStats) (rs : List ReliabilityStats) :
    (aggregateReliability (s :: rs)).2 ≤ s.total := by
  unfold aggregateReliability
  -- foldl with Nat.min starting from s.total can only decrease the
  -- second component. Formalize by induction on rs with a strengthened
  -- IH that covers arbitrary starting totals.
  have aux : ∀ (xs : List ReliabilityStats) (init : Nat) (accF : Float),
      (xs.foldl
        (fun (accRel, accSz) x =>
          (floatMin accRel (reliabilityScore x), Nat.min accSz x.total))
        (accF, init)).2 ≤ init := by
    intro xs
    induction xs with
    | nil => intro init _; exact Nat.le_refl _
    | cons y ys ih =>
      intro init accF
      simp only [List.foldl]
      exact Nat.le_trans (ih _ _) (Nat.min_le_left _ _)
  exact aux rs s.total (reliabilityScore s)

end Veritas.Learning
