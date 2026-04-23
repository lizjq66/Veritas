/-
  Veritas.Gates.PortfolioGate — Gate 3: portfolio interference.

  Given existing positions and a new proposed trade, decide whether
  adding the trade would violate portfolio-level constraints.

  v0.2 upgrade: exposure is measured with correlation weighting.
  Same-asset positions default to correlation 1; unknown cross-asset
  pairs default to 0; explicit entries override both.

  v0.2 Slice 5: the whole arithmetic stack runs on exact `Rat`.

  Reject paths:
    - direction_conflicts_existing_position
    - gross_exposure_cap_non_positive
    - portfolio_already_at_correlation_weighted_cap
  Resize path:
    - correlation-adjusted exposure would breach the cap; resize down
-/
import Veritas.Gates.Types
import Mathlib.Algebra.Order.Ring.Abs
import Mathlib.Algebra.Order.Ring.Rat
import Mathlib.Tactic.Linarith

namespace Veritas.Gates

open Veritas

/-- Absolute |correlation| between two assets. Same-asset pairs → 1
    (even without an explicit entry); unknown cross-asset pairs → 0. -/
def correlationBetween
    (table : List CorrelationEntry) (a b : String) : Rat :=
  if a == b then 1
  else
    match table.find?
      (fun e => (e.assetA == a && e.assetB == b)
              ∨ (e.assetA == b && e.assetB == a)) with
    | some e => |e.coefficient|
    | none   => 0

/-- Sum of each existing position's absolute notional weighted by
    |correlation| with the proposed asset. -/
def correlationAdjustedExposure
    (port : Portfolio) (p : TradeProposal) : Rat :=
  port.positions.foldl
    (fun acc pos =>
      acc +
      |pos.entryPrice * pos.size| *
        correlationBetween port.correlations pos.asset p.asset)
    0

/-- **Proposal-axis projected exposure bound.**

    For each existing position, contributes
    `|notional| × volatility × |correlation with proposal.asset|`;
    the proposal's own contribution is `|notional| × volatility`.

    What this quantity actually bounds (by triangle inequality):

        |x₀·σ₀ + Σᵢ xᵢ·σᵢ·ρ₀ᵢ|   ≤   portfolioVarBound port p

    i.e. the absolute **projected exposure** of the combined
    portfolio along the proposal's asset return factor. Equivalently:
    "how much combined directional risk would I take on along the
    proposal's own volatility axis."

    What it does **NOT** bound in general:
    the full-portfolio quadratic-form VaR `√xᵀΣx`. The formula
    consults only correlations **between each existing position and
    the proposal** (`ρ₀ᵢ`); it ignores correlations **among existing
    positions** (`ρᵢⱼ` for `i,j ≠ 0`), so two mutually-correlated
    existing positions can contribute 0 to this bound (if each is
    uncorrelated with the proposal) while still jointly carrying
    real portfolio variance.

    `AccountConstraints.dailyVarLimit` **is** a limit on this
    projected exposure. That is the fixed, committed semantic of the
    field. Full-portfolio `√xᵀΣx` gating is not a property of
    `dailyVarLimit`; if Veritas ever adds full-portfolio VaR
    gating, it will ship as a separate constraint field and a
    separate gate branch, not by redefining `dailyVarLimit`. See
    `docs/var-audit-2026-04-23.md` for the scope-of-validity
    analysis and worked counter-examples.

    The projected-exposure bound is an *exact* upper bound inside
    `Rat` arithmetic — no square roots, no numeric approximation —
    which is why this definition stays in Gate 3's hot path. -/
def portfolioVarBound
    (port : Portfolio) (p : TradeProposal) : Rat :=
  let existing := port.positions.foldl
    (fun acc pos =>
      acc +
      |pos.entryPrice * pos.size| * pos.volatility *
        correlationBetween port.correlations pos.asset p.asset)
    0
  existing + |p.notionalUsd| * p.volatility

/-- Does any existing position on the same asset carry the opposite
    direction? Cross-asset opposite directions are not a conflict. -/
def hasDirectionConflict
    (positions : List Position) (p : TradeProposal) : Bool :=
  positions.any
    (fun pos => pos.asset == p.asset && pos.direction != p.direction)

/-- Gate 3: check portfolio interference under correlation weighting
    and (optionally) a linear VaR upper bound.

    The gross-exposure cap is always enforced. The VaR bound is
    enforced additionally iff the caller supplies a non-zero
    `dailyVarLimit` in `AccountConstraints`. Default `dailyVarLimit = 0`
    preserves the v0.2 single-check behavior. -/
def checkPortfolio
    (p : TradeProposal) (port : Portfolio) (c : AccountConstraints) : Verdict :=
  if hasDirectionConflict port.positions p then
    .Reject ["direction_conflicts_existing_position"]
  else
    let adjusted := correlationAdjustedExposure port p
    let cap := c.equity * port.maxGrossExposureFraction
    let proposed := |p.notionalUsd|
    let total := adjusted + proposed
    if cap ≤ 0 then
      .Reject ["gross_exposure_cap_non_positive"]
    else if c.dailyVarLimit > 0 ∧ portfolioVarBound port p > c.dailyVarLimit then
      .Reject ["portfolio_var_limit_exceeded"]
    else if total ≤ cap then
      .Approve
    else
      let headroom := cap - adjusted
      if headroom ≤ 0 then
        .Reject ["portfolio_already_at_correlation_weighted_cap"]
      else
        .Resize headroom

-- ── Soundness contract ────────────────────────────────────────────

/-- Gate 3 soundness (approve, gross-exposure): correlation-adjusted
    exposure plus the proposal's absolute notional stays within the
    gross-exposure cap. -/
theorem checkPortfolio_approve_respects_cap
    (p : TradeProposal) (port : Portfolio) (c : AccountConstraints)
    (h : checkPortfolio p port c = .Approve) :
    correlationAdjustedExposure port p + |p.notionalUsd|
      ≤ c.equity * port.maxGrossExposureFraction := by
  have h' :
      (if hasDirectionConflict port.positions p then
        Verdict.Reject ["direction_conflicts_existing_position"]
       else if c.equity * port.maxGrossExposureFraction ≤ 0 then
        Verdict.Reject ["gross_exposure_cap_non_positive"]
       else if c.dailyVarLimit > 0 ∧ portfolioVarBound port p > c.dailyVarLimit then
        Verdict.Reject ["portfolio_var_limit_exceeded"]
       else if correlationAdjustedExposure port p + |p.notionalUsd|
              ≤ c.equity * port.maxGrossExposureFraction then
        Verdict.Approve
       else if c.equity * port.maxGrossExposureFraction
               - correlationAdjustedExposure port p ≤ 0 then
        Verdict.Reject ["portfolio_already_at_correlation_weighted_cap"]
       else
        Verdict.Resize (c.equity * port.maxGrossExposureFraction
                         - correlationAdjustedExposure port p))
        = .Approve := h
  split at h'
  · cases h'
  · split at h'
    · cases h'
    · split at h'
      · cases h'
      · split at h'
        · rename_i hle; exact hle
        · split at h'
          · cases h'
          · cases h'

/-- Gate 3 soundness (approve, projected-exposure): when the caller
    sets a positive `dailyVarLimit`, any Approve implies the
    portfolio's proposal-axis projected-exposure bound
    (`portfolioVarBound`) stays within it.

    **Semantics caveat.** `dailyVarLimit` is a limit on
    `portfolioVarBound` as defined above, which bounds projected
    exposure along the proposal's asset — it is *not* a limit on
    full-portfolio `√xᵀΣx`. See `portfolioVarBound`'s docstring
    and `docs/var-audit-2026-04-23.md`. -/
theorem checkPortfolio_approve_respects_var_bound
    (p : TradeProposal) (port : Portfolio) (c : AccountConstraints)
    (hpos : c.dailyVarLimit > 0)
    (h : checkPortfolio p port c = .Approve) :
    portfolioVarBound port p ≤ c.dailyVarLimit := by
  have h' :
      (if hasDirectionConflict port.positions p then
        Verdict.Reject ["direction_conflicts_existing_position"]
       else if c.equity * port.maxGrossExposureFraction ≤ 0 then
        Verdict.Reject ["gross_exposure_cap_non_positive"]
       else if c.dailyVarLimit > 0 ∧ portfolioVarBound port p > c.dailyVarLimit then
        Verdict.Reject ["portfolio_var_limit_exceeded"]
       else if correlationAdjustedExposure port p + |p.notionalUsd|
              ≤ c.equity * port.maxGrossExposureFraction then
        Verdict.Approve
       else if c.equity * port.maxGrossExposureFraction
               - correlationAdjustedExposure port p ≤ 0 then
        Verdict.Reject ["portfolio_already_at_correlation_weighted_cap"]
       else
        Verdict.Resize (c.equity * port.maxGrossExposureFraction
                         - correlationAdjustedExposure port p))
        = .Approve := h
  split at h'
  · cases h'
  · split at h'
    · cases h'
    · split at h'
      · cases h'
      · -- In this branch, the VaR guard did NOT fire — its negation
        -- combined with hpos gives the desired inequality.
        rename_i hVarGuardFalse
        by_contra hgt
        exact hVarGuardFalse ⟨hpos, lt_of_not_ge hgt⟩

/-- Gate 3 resize soundness (cap): the correlation-adjusted exposure
    plus the absolute value of the resize's notional also stays within
    the cap. In the Resize branch the resize value equals
    `cap - adjusted` and the branch's precondition guarantees
    `cap - adjusted > 0`, so its absolute value equals itself and
    `adjusted + (cap - adjusted) = cap`. Twin of
    `checkPortfolio_approve_respects_cap`; feeds the composed
    certificate-level Gate 3 cap theorem. -/
theorem checkPortfolio_resize_respects_cap
    (p : TradeProposal) (port : Portfolio) (c : AccountConstraints)
    (m : Rat)
    (h : checkPortfolio p port c = .Resize m) :
    correlationAdjustedExposure port p + |m|
      ≤ c.equity * port.maxGrossExposureFraction := by
  have h' :
      (if hasDirectionConflict port.positions p then
        Verdict.Reject ["direction_conflicts_existing_position"]
       else if c.equity * port.maxGrossExposureFraction ≤ 0 then
        Verdict.Reject ["gross_exposure_cap_non_positive"]
       else if c.dailyVarLimit > 0 ∧ portfolioVarBound port p > c.dailyVarLimit then
        Verdict.Reject ["portfolio_var_limit_exceeded"]
       else if correlationAdjustedExposure port p + |p.notionalUsd|
              ≤ c.equity * port.maxGrossExposureFraction then
        Verdict.Approve
       else if c.equity * port.maxGrossExposureFraction
               - correlationAdjustedExposure port p ≤ 0 then
        Verdict.Reject ["portfolio_already_at_correlation_weighted_cap"]
       else
        Verdict.Resize (c.equity * port.maxGrossExposureFraction
                         - correlationAdjustedExposure port p))
        = .Resize m := h
  split at h'
  · cases h'
  · split at h'
    · cases h'
    · split at h'
      · cases h'
      · split at h'
        · cases h'
        · split at h'
          · cases h'
          · injection h' with hm
            -- hm : cap - adjusted = m
            -- Position 5 (oldest-first) is the Resize branch's
            -- `¬ (cap - adjusted ≤ 0)` guard.
            rename_i _hdc _hcap _hvar _htotal hheadroom
            have hpos : 0 < c.equity * port.maxGrossExposureFraction
                          - correlationAdjustedExposure port p :=
              lt_of_not_ge hheadroom
            have hmpos : 0 < m := by rw [← hm]; exact hpos
            have habs : |m| = m := abs_of_pos hmpos
            rw [habs, ← hm]
            linarith

/-- Gate 3's resize value is strictly positive: the Resize branch is
    only reached past the `cap - adjusted ≤ 0` rejection, and the
    resize value equals `cap - adjusted`. -/
theorem checkPortfolio_resize_nonneg
    (p : TradeProposal) (port : Portfolio) (c : AccountConstraints)
    (m : Rat)
    (h : checkPortfolio p port c = .Resize m) :
    0 < m := by
  have h' :
      (if hasDirectionConflict port.positions p then
        Verdict.Reject ["direction_conflicts_existing_position"]
       else if c.equity * port.maxGrossExposureFraction ≤ 0 then
        Verdict.Reject ["gross_exposure_cap_non_positive"]
       else if c.dailyVarLimit > 0 ∧ portfolioVarBound port p > c.dailyVarLimit then
        Verdict.Reject ["portfolio_var_limit_exceeded"]
       else if correlationAdjustedExposure port p + |p.notionalUsd|
              ≤ c.equity * port.maxGrossExposureFraction then
        Verdict.Approve
       else if c.equity * port.maxGrossExposureFraction
               - correlationAdjustedExposure port p ≤ 0 then
        Verdict.Reject ["portfolio_already_at_correlation_weighted_cap"]
       else
        Verdict.Resize (c.equity * port.maxGrossExposureFraction
                         - correlationAdjustedExposure port p))
        = .Resize m := h
  split at h'
  · cases h'
  · split at h'
    · cases h'
    · split at h'
      · cases h'
      · split at h'
        · cases h'
        · split at h'
          · cases h'
          · injection h' with hm
            rename_i _hdc _hcap _hvar _htotal hheadroom
            rw [← hm]
            exact lt_of_not_ge hheadroom

/-- Gate 3 resize soundness (projected-exposure): when the caller
    sets a positive `dailyVarLimit`, any Resize verdict also implies
    the input proposal's `portfolioVarBound` stays within the limit.
    The VaR guard is an earlier branch than the Resize path in the
    if-else chain, so by the time we reach Resize the guard must
    have failed to fire — giving us exactly this bound. Twin of
    `_approve_respects_var_bound` for the Resize path.

    **Semantics caveat.** See `portfolioVarBound`'s docstring:
    `dailyVarLimit` bounds projected exposure along the proposal's
    asset, not full-portfolio `√xᵀΣx`. -/
theorem checkPortfolio_resize_respects_var_bound
    (p : TradeProposal) (port : Portfolio) (c : AccountConstraints)
    (m : Rat)
    (hpos : c.dailyVarLimit > 0)
    (h : checkPortfolio p port c = .Resize m) :
    portfolioVarBound port p ≤ c.dailyVarLimit := by
  have h' :
      (if hasDirectionConflict port.positions p then
        Verdict.Reject ["direction_conflicts_existing_position"]
       else if c.equity * port.maxGrossExposureFraction ≤ 0 then
        Verdict.Reject ["gross_exposure_cap_non_positive"]
       else if c.dailyVarLimit > 0 ∧ portfolioVarBound port p > c.dailyVarLimit then
        Verdict.Reject ["portfolio_var_limit_exceeded"]
       else if correlationAdjustedExposure port p + |p.notionalUsd|
              ≤ c.equity * port.maxGrossExposureFraction then
        Verdict.Approve
       else if c.equity * port.maxGrossExposureFraction
               - correlationAdjustedExposure port p ≤ 0 then
        Verdict.Reject ["portfolio_already_at_correlation_weighted_cap"]
       else
        Verdict.Resize (c.equity * port.maxGrossExposureFraction
                         - correlationAdjustedExposure port p))
        = .Resize m := h
  split at h'
  · cases h'
  · split at h'
    · cases h'
    · split at h'
      · cases h'
      · split at h'
        · cases h'
        · split at h'
          · cases h'
          · -- Resize branch. Position 3 (oldest-first) is the
            -- VaR guard's negation: ¬ (dailyVarLimit > 0 ∧ varBound > limit).
            rename_i _hdc _hcap hvarguard _htotal _hheadroom
            by_contra hgt
            exact hvarguard ⟨hpos, lt_of_not_ge hgt⟩

/-- Monotonicity of `portfolioVarBound` in the absolute value of the
    proposal's notional, given non-negative volatility. Since
    `portfolioVarBound` decomposes as (existing positions' contribution,
    depending only on `p.asset`) + `|p.notionalUsd| * p.volatility`, a
    tighter |notional| tightens the bound when `volatility ≥ 0`. Lets
    the certificate-level VaR theorem transfer a bound at the Gate-3
    input down to the potentially smaller final notional. -/
theorem portfolioVarBound_mono_in_abs_notional
    (port : Portfolio) (p : TradeProposal) (m k : Rat)
    (hvol : 0 ≤ p.volatility)
    (hle : |m| ≤ |k|) :
    portfolioVarBound port { p with notionalUsd := m }
      ≤ portfolioVarBound port { p with notionalUsd := k } := by
  -- Both sides share the same `existing` term (fold over port.positions
  -- depending only on p.asset, which is preserved by struct update).
  -- `simp only [portfolioVarBound]` beta-reduces the `let existing`
  -- binding so the inequality reduces to `|m|·vol ≤ |k|·vol`.
  simp only [portfolioVarBound]
  have hmul : |m| * p.volatility ≤ |k| * p.volatility :=
    mul_le_mul_of_nonneg_right hle hvol
  linarith

/-- Gate 3 resize is bounded above by the **submitted proposal's**
    notional whenever that notional is non-negative: the Resize branch
    is only reached when `adjusted + |p.notionalUsd| > cap`, so
    `cap - adjusted < |p.notionalUsd| = p.notionalUsd` (using the
    non-negativity hypothesis). Needed by the certificate-level
    composition theorem so Gate 3 can't silently widen what Gate 2
    approved or resized to. -/
theorem checkPortfolio_resize_at_most_nonneg_proposal
    (p : TradeProposal) (port : Portfolio) (c : AccountConstraints)
    (m : Rat)
    (hp : 0 ≤ p.notionalUsd)
    (h : checkPortfolio p port c = .Resize m) :
    m ≤ p.notionalUsd := by
  have h' :
      (if hasDirectionConflict port.positions p then
        Verdict.Reject ["direction_conflicts_existing_position"]
       else if c.equity * port.maxGrossExposureFraction ≤ 0 then
        Verdict.Reject ["gross_exposure_cap_non_positive"]
       else if c.dailyVarLimit > 0 ∧ portfolioVarBound port p > c.dailyVarLimit then
        Verdict.Reject ["portfolio_var_limit_exceeded"]
       else if correlationAdjustedExposure port p + |p.notionalUsd|
              ≤ c.equity * port.maxGrossExposureFraction then
        Verdict.Approve
       else if c.equity * port.maxGrossExposureFraction
               - correlationAdjustedExposure port p ≤ 0 then
        Verdict.Reject ["portfolio_already_at_correlation_weighted_cap"]
       else
        Verdict.Resize (c.equity * port.maxGrossExposureFraction
                         - correlationAdjustedExposure port p))
        = .Resize m := h
  split at h'
  · cases h'
  · split at h'
    · cases h'
    · split at h'
      · cases h'
      · split at h'
        · cases h'
        · split at h'
          · cases h'
          · injection h' with hm
            -- Rename the five anonymous hypotheses introduced by the
            -- successive `split at h'` calls. Order matches introduction
            -- order (oldest first).
            rename_i _hdc _hcap _hvar htotal _hheadroom
            -- htotal : ¬ (adjusted + |p.notionalUsd| ≤ cap)
            have habs : |p.notionalUsd| = p.notionalUsd := abs_of_nonneg hp
            rw [habs] at htotal
            have hgt := lt_of_not_ge htotal
            -- hgt : cap < adjusted + p.notionalUsd
            rw [← hm]
            linarith

end Veritas.Gates
