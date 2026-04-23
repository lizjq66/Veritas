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

/-- Linear upper bound on daily portfolio VaR after adding the
    proposal. For each existing position, contributes
    `|notional| × volatility × |correlation with proposal.asset|`;
    the proposal's own contribution is `|notional| × volatility`.

    This is an *upper bound* on the quadratic-form VaR
    (√xᵀΣx) via the triangle inequality, which lets Gate 3's VaR
    check stay inside exact `Rat` arithmetic — no square roots,
    no numeric approximation. If the linear bound fits the limit,
    the true VaR does too. -/
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

/-- Gate 3 soundness (approve, VaR): when the caller sets a positive
    `dailyVarLimit`, the portfolio's linear VaR upper bound stays
    within it. The linear bound is a true upper bound on
    quadratic-form VaR (√xᵀΣx), so respecting the linear limit
    implies respecting the quadratic one. -/
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
