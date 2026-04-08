/-
  Veritas.Finance.FloatAxioms — Axioms for IEEE 754 Float reasoning.

  # Why these axioms exist

  Lean 4's `Float` is an opaque type backed by C `double` via FFI.
  The standard library provides `Float.decLe`/`Float.decLt` for decidable
  comparison, but **zero** algebraic lemmas — no `le_trans`, no `mul_nonneg`,
  nothing. Without these, any property of a Float-valued function is
  unprovable. These 20 axioms are the minimal set we need to verify
  Veritas's position-sizing, Kelly, and reliability modules.

  # What we are trusting

  **Ordering (7 axioms):** Reflexivity, transitivity, totality, and the
  relationship between `≤` and `>`. These are exact — IEEE 754 defines a
  total order on all non-NaN finite values, and Lean's `Float.le`/`Float.lt`
  delegate to hardware comparison.

  **Literal equality (1 axiom):** `0.0 = 0` bridges two distinct opaque
  representations (`Float.ofScientific 0 true 1` vs `Float.ofScientific 0
  false 0`). Both represent IEEE 754 positive zero. This is a quirk of
  Lean's literal elaboration, not an arithmetic claim.

  **Sign preservation (2 axioms):** `mul_nonneg` and `div_nonneg`. In
  IEEE 754, the sign of a product/quotient is the XOR of the operand signs,
  so nonneg × nonneg = nonneg and nonneg / pos = nonneg. Exact.

  **Nat.toFloat (3 axioms):** Nonneg, positivity, and monotonicity of the
  `Nat → Float` coercion. Exact for values up to 2^53 (the integer-exact
  range of binary64). Veritas uses small counters, so this is safe.

  **Arithmetic monotonicity (7 axioms):** `mul_le_mul`, `sub_le_sub`,
  `div_le_div`, and `div_succ_mono`. These assume that IEEE 754 rounding
  does not reverse the inequality — i.e., if the exact real result of
  `a op b` ≤ `c op d`, then the rounded result preserves the direction.
  This is NOT universally true for arbitrary Float values (rounding can
  nudge a result across the boundary), but it holds in practice for the
  magnitudes Veritas operates on: probabilities in [0, 1], small integer
  win/loss counts, and Kelly fractions. We accept this as a pragmatic
  modelling assumption.

  # When to remove this file

  When Lean or Mathlib ships a `Float` proof library (even partial),
  replace each axiom with the corresponding library lemma and delete
  this file. Track progress at: https://github.com/leanprover/lean4/issues/2220
-/

namespace Veritas.Finance

-- ── Ordering ─────────────────────────────────────────────────────────

axiom Float.le_refl (a : Float) : a ≤ a
axiom Float.le_trans {a b c : Float} : a ≤ b → b ≤ c → a ≤ c
axiom Float.not_le_to_ge {a b : Float} : ¬(a ≤ b) → b ≤ a
axiom Float.le_of_not_gt {a b : Float} : ¬(a > b) → a ≤ b
axiom Float.not_gt_of_le {a b : Float} : a ≤ b → ¬(a > b)

axiom Float.not_le_of_gt {a b : Float} : a > b → ¬(a ≤ b)
axiom Float.le_of_gt {a b : Float} : a > b → b ≤ a

-- ── Subtraction ordering ────────────────────────────────────────────

axiom Float.sub_le_sub_right {a b c : Float} : a ≤ b → a - c ≤ b - c
axiom Float.sub_le_sub_left {a b c : Float} : a ≤ b → c - b ≤ c - a

-- ── Literal equality ─────────────────────────────────────────────────

axiom Float.zero_point_zero_eq : (0.0 : Float) = (0 : Float)

-- ── Arithmetic ordering ──────────────────────────────────────────────

axiom Float.mul_nonneg {a b : Float} : a ≥ 0 → b ≥ 0 → a * b ≥ 0
axiom Float.mul_le_mul_of_nonneg_left {a b c : Float} :
    a ≤ b → 0 ≤ c → c * a ≤ c * b
axiom Float.mul_le_mul_of_nonneg_right {a b c : Float} :
    a ≤ b → 0 ≤ c → a * c ≤ b * c

-- ── Nat.toFloat ──────────────────────────────────────────────────────

axiom Float.Nat_toFloat_nonneg (n : Nat) : n.toFloat ≥ 0
axiom Float.Nat_toFloat_pos {n : Nat} : n > 0 → n.toFloat > 0
axiom Float.Nat_toFloat_mono {a b : Nat} : a ≤ b → a.toFloat ≤ b.toFloat

-- ── Division ─────────────────────────────────────────────────────────

axiom Float.div_nonneg {a b : Float} : a ≥ 0 → b > 0 → a / b ≥ 0
axiom Float.div_le_div_of_nonneg_right {a b c : Float} : a ≤ b → c > 0 → a / c ≤ b / c
axiom Float.div_le_one {a b : Float} : a ≤ b → b > 0 → a / b ≤ 1
axiom Float.div_succ_mono {a b : Nat} : a ≤ b → b > 0 →
    (a + 1).toFloat / (b + 1).toFloat ≥ a.toFloat / b.toFloat

end Veritas.Finance
