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


-- ── Bayesian reliability (v0.4 Slice 1) ────────────────────────────
--
-- The `ReliabilityStats`/`reliabilityScore` pair above is a frequentist
-- point estimate: `wins / total`, with a 1/2 fallback at zero-sample.
-- That leaks two pathologies: (a) one-shot wins give reliability 1.0,
-- pushing Gate 2 straight to the Kelly ceiling; (b) zero-observation
-- branches read as 0.5 with no uncertainty surface. `BetaPosterior`
-- replaces the point estimate with a Beta(α, β) posterior, defaulting
-- to the uniform Beta(1, 1) prior (Laplace smoothing).
--
-- This slice adds the type, the posterior-mean computation, and three
-- foundational theorems. Wiring it into Gate 2 (replacing
-- `calculatePositionSize`'s frequentist reliability input) is a
-- follow-on slice so existing Gate-2 theorems can be updated in one
-- deliberate step.

/-- Beta-posterior reliability estimate from observed binary outcomes,
    with a Beta(α₀, β₀) prior over the underlying win rate. Default
    priors `α₀ = β₀ = 1` give Laplace smoothing: zero observations
    read as `1/2`, and a single win/loss updates gently toward the
    evidence rather than saturating. -/
structure BetaPosterior where
  successes : Nat
  failures : Nat
  priorAlpha : Rat := 1
  priorBeta : Rat := 1
  deriving Repr, Inhabited

namespace BetaPosterior

/-- Posterior mean of a Beta(α₀ + successes, β₀ + failures) posterior,
    expressed as an exact `Rat`. This is the point estimate Gate 2
    consumes (in the follow-on slice) once the frequentist input is
    replaced. -/
def posteriorMean (b : BetaPosterior) : Rat :=
  ((b.successes : Rat) + b.priorAlpha) /
  (((b.successes + b.failures) : Rat) + b.priorAlpha + b.priorBeta)

/-- Posterior mean is in `[0, 1]`. Requires non-negative priors and a
    strictly positive prior sum (the Beta distribution is undefined at
    `α₀ = β₀ = 0` anyway). -/
theorem posteriorMean_bounded (b : BetaPosterior)
    (hα : 0 ≤ b.priorAlpha) (hβ : 0 ≤ b.priorBeta)
    (hpos : 0 < b.priorAlpha + b.priorBeta) :
    0 ≤ posteriorMean b ∧ posteriorMean b ≤ 1 := by
  unfold posteriorMean
  have hnum : 0 ≤ (b.successes : Rat) + b.priorAlpha := by positivity
  have hSF : 0 ≤ ((b.successes + b.failures) : Rat) := by positivity
  have hden : 0 < ((b.successes + b.failures) : Rat)
                    + b.priorAlpha + b.priorBeta := by linarith
  refine ⟨div_nonneg hnum (le_of_lt hden), ?_⟩
  rw [div_le_one hden]
  have hF : 0 ≤ (b.failures : Rat) := by positivity
  linarith

/-- Adding successes never decreases the posterior mean. The
    Bayesian analogue of `reliabilityUpdate_monotone_on_wins`, but
    unconditionally — no `total > 0` premise needed, because the
    prior term keeps the denominator positive even at zero
    observations. -/
theorem posteriorMean_monotone_in_successes
    (b : BetaPosterior) (k : Nat)
    (hβ : 0 ≤ b.priorBeta)
    (hpos : 0 < b.priorAlpha + b.priorBeta) :
    posteriorMean b
      ≤ posteriorMean { b with successes := b.successes + k } := by
  unfold posteriorMean
  -- dsimp reduces the struct-update projections to their plain forms
  -- ({b with successes := s'}.successes → s', .failures → b.failures,
  -- .priorAlpha → b.priorAlpha, .priorBeta → b.priorBeta) so that the
  -- subsequent `rw` and `nlinarith` can match.
  dsimp only
  push_cast
  have hS : 0 ≤ (b.successes : Rat) := by positivity
  have hF : 0 ≤ (b.failures : Rat) := by positivity
  have hk : 0 ≤ (k : Rat) := by positivity
  have hden1 : 0 < (b.successes : Rat) + (b.failures : Rat)
                     + b.priorAlpha + b.priorBeta := by linarith
  have hden2 : 0 < (b.successes : Rat) + (k : Rat) + (b.failures : Rat)
                     + b.priorAlpha + b.priorBeta := by linarith
  rw [div_le_div_iff₀ hden1 hden2]
  -- Goal after cross-multiplication: reduces to 0 ≤ k·(F + β).
  nlinarith [mul_nonneg hk hF, mul_nonneg hk hβ]

/-- The uniform prior with no observations yields exactly `1/2` —
    the canonical "I don't know" state Gate 2 sees before any
    evidence arrives. Matches `reliabilityScore`'s `total = 0`
    fallback, so dropping `BetaPosterior` into Gate 2 preserves
    the zero-observation behavior. -/
theorem posteriorMean_uniform_prior_empty :
    posteriorMean { successes := 0, failures := 0 } = 1 / 2 := by
  unfold posteriorMean
  norm_num

/-- **Pessimistic posterior mean** for small-sample / uncertainty-aware
    sizing. Computes the posterior mean **as if** `k` additional
    failures had been observed:

      pessimisticMean b k
        = posteriorMean { b with failures := b.failures + k }
        = (successes + α) / (total + k + α + β)

    Equivalent to updating under a more skeptical `Beta(α, β + k)`
    prior — a legitimate Bayesian operation, just reframed for the
    caller as "how much would my size change if I pretended I'd seen
    `k` more losses?" Stays in exact `Rat` arithmetic (no quantile
    computation / no √), and serves as the calibration primitive for
    v0.4's "confidence-bound-aware sizing" story.

    Why a shift rather than a true statistical lower confidence
    bound: a Beta-distribution quantile at non-trivial confidence
    level requires the inverse-Beta-CDF, which escapes exact
    rationals. The failure-shift is the pragmatic approximation
    that preserves Veritas's no-Float-axiom arithmetic guarantee
    while still delivering the "small samples get smaller sizing"
    behavior traders want. -/
def pessimisticMean (b : BetaPosterior) (k : Nat) : Rat :=
  posteriorMean { b with failures := b.failures + k }

/-- Pessimistic mean never exceeds the ordinary posterior mean. -/
theorem pessimisticMean_le_posteriorMean
    (b : BetaPosterior) (k : Nat)
    (hα : 0 ≤ b.priorAlpha) (_hβ : 0 ≤ b.priorBeta)
    (hpos : 0 < b.priorAlpha + b.priorBeta) :
    pessimisticMean b k ≤ posteriorMean b := by
  unfold pessimisticMean posteriorMean
  dsimp only
  -- Goal reduces to:
  --   (S + α) / (S + F + k + α + β) ≤ (S + α) / (S + F + α + β).
  -- Numerator non-negative; right denominator ≤ left denominator;
  -- dividing a non-negative numerator by a larger positive
  -- denominator gives a smaller value.
  push_cast
  have hS : 0 ≤ (b.successes : Rat) := by positivity
  have hF : 0 ≤ (b.failures : Rat) := by positivity
  have hk : 0 ≤ (k : Rat) := by positivity
  have hden1 : 0 < (b.successes : Rat) + b.failures + b.priorAlpha + b.priorBeta := by
    linarith
  have hden2 : 0 < (b.successes : Rat) + (b.failures + k) + b.priorAlpha + b.priorBeta := by
    linarith
  rw [div_le_div_iff₀ hden2 hden1]
  have hnum : 0 ≤ (b.successes : Rat) + b.priorAlpha := by positivity
  nlinarith [mul_nonneg hnum hk]

/-- Pessimistic mean is in `[0, 1]`, inherited from
    `posteriorMean_bounded` applied to the failure-shifted
    posterior. -/
theorem pessimisticMean_bounded
    (b : BetaPosterior) (k : Nat)
    (hα : 0 ≤ b.priorAlpha) (hβ : 0 ≤ b.priorBeta)
    (hpos : 0 < b.priorAlpha + b.priorBeta) :
    0 ≤ pessimisticMean b k ∧ pessimisticMean b k ≤ 1 :=
  posteriorMean_bounded { b with failures := b.failures + k } hα hβ hpos

end BetaPosterior

end Veritas.Learning
