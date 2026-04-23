"""Public theorem registry — what Veritas claims is proved.

Each entry names one theorem Veritas ships as a trust signal: its Lean
file, its proof status, a natural-language statement, and any
Veritas-declared axioms it transitively depends on.

Post v0.2 Slice 5 (``935b96c``) Veritas declares zero axioms of its
own; proofs close under Lean's core (``propext``, ``Classical.choice``,
``Quot.sound``) plus stdlib / Mathlib lemmas. ``axioms_used`` therefore
lists only Veritas-specific axioms — always ``[]`` today. When a
future theorem requires a new Veritas axiom, that axiom is declared
in Lean and surfaced here.

v0.3 Slice 5 added ``compute_theorem_registry_sha()`` and the
``GET /verify/theorems`` / ``/verify/pubkey`` exposure so callers can
pin the registry's content against the ``build_sha`` of the compiled
``veritas-core`` binary.

When you add a new theorem to Lean under ``Veritas/Gates``,
``Veritas/Strategy``, ``Veritas/Finance``, or ``Veritas/Learning``,
you must ALSO add its entry here. The test suite treats the registry
as the public contract and any omission silently downgrades Veritas's
trust surface without warning.
"""

from __future__ import annotations

import hashlib
import json

THEOREMS: dict[str, dict] = {
    # ── Gate 2 bounds (Finance.PositionSizing) ─────────────────────
    "positionSize_nonneg": {
        "gate": 2,
        "file": "Veritas/Finance/PositionSizing.lean",
        "status": "proven",
        "statement_natural_language":
            "Post-exploration position size is always non-negative.",
        "axioms_used": [],
    },
    "positionSize_capped": {
        "gate": 2,
        "file": "Veritas/Finance/PositionSizing.lean",
        "status": "proven",
        "statement_natural_language":
            "Post-exploration position size never exceeds 25% of equity.",
        "axioms_used": [],
    },
    "positionSize_monotone_in_reliability": {
        "gate": 2,
        "file": "Veritas/Finance/PositionSizing.lean",
        "status": "proven",
        "statement_natural_language":
            "Higher reliability never produces a smaller post-exploration position.",
        "axioms_used": [],
    },
    "positionSize_zero_at_no_edge": {
        "gate": 2,
        "file": "Veritas/Finance/PositionSizing.lean",
        "status": "proven",
        "statement_natural_language":
            "Post-exploration position is zero when reliability ≤ 0.5 (no edge).",
        "axioms_used": [],
    },
    "positionSize_explorationCapped": {
        "gate": 2,
        "file": "Veritas/Finance/PositionSizing.lean",
        "status": "proven",
        "statement_natural_language":
            "During exploration, position is fixed at 1% of equity.",
        "axioms_used": [],
    },
    # ── Kelly layer (Finance.Kelly) ────────────────────────────────
    "kellyFraction_nonneg": {
        "gate": 2,
        "file": "Veritas/Finance/Kelly.lean",
        "status": "proven",
        "statement_natural_language":
            "The Kelly fraction is always non-negative.",
        "axioms_used": [],
    },
    "kellyFraction_mono": {
        "gate": 2,
        "file": "Veritas/Finance/Kelly.lean",
        "status": "proven",
        "statement_natural_language":
            "The Kelly fraction is monotone in win probability.",
        "axioms_used": [],
    },
    # ── Exit classification (Strategy.ExitLogic) ───────────────────
    "exitReason_exhaustive": {
        "gate": "classify_exit",
        "file": "Veritas/Strategy/ExitLogic.lean",
        "status": "proven",
        "statement_natural_language":
            "Every exit is classified into exactly one of three reasons "
            "(assumption_met | assumption_broke | stop_loss).",
        "axioms_used": [],
    },
    # ── Reliability update (Learning.Reliability) ──────────────────
    "reliabilityUpdate_monotone_on_wins": {
        "gate": "learning",
        "file": "Veritas/Learning/Reliability.lean",
        "status": "proven",
        "statement_natural_language":
            "After a win, reliability never decreases.",
        "axioms_used": [],
    },
    "reliabilityUpdate_bounded": {
        "gate": "learning",
        "file": "Veritas/Learning/Reliability.lean",
        "status": "proven",
        "statement_natural_language":
            "Reliability is always in [0, 1].",
        "axioms_used": [],
    },
    # ── Multi-assumption aggregation (v0.2 Slice 4 + 5) ────────────
    "aggregateReliability_empty": {
        "gate": "learning",
        "file": "Veritas/Learning/Reliability.lean",
        "status": "proven",
        "statement_natural_language":
            "Aggregating no assumption stats yields the default "
            "(reliability = 0.5, sample_size = 0) pair.",
        "axioms_used": [],
    },
    "aggregateReliability_singleton": {
        "gate": "learning",
        "file": "Veritas/Learning/Reliability.lean",
        "status": "proven",
        "statement_natural_language":
            "Aggregating a single-element list returns that element's "
            "own reliability score and total. Aggregation is "
            "idempotent for callers with exactly one assumption.",
        "axioms_used": [],
    },
    "aggregateReliability_sampleSize_le_head": {
        "gate": "learning",
        "file": "Veritas/Learning/Reliability.lean",
        "status": "proven",
        "statement_natural_language":
            "The aggregate sample size never exceeds any input's total. "
            "Consequently, one under-sampled assumption forces the whole "
            "proposal into Gate 2's exploration phase.",
        "axioms_used": [],
    },
    "aggregateReliability_score_le_each": {
        "gate": "learning",
        "file": "Veritas/Learning/Reliability.lean",
        "status": "proven",
        "statement_natural_language":
            "Aggregate reliability is ≤ every input's reliability — the "
            "aggregation is conservative. Unlocked by the v0.2 Slice 5 "
            "move to exact Rat.",
        "axioms_used": [],
    },
    # ── v0.4 Slice 1: Bayesian reliability groundwork ─────────────
    # Adds a Beta(α, β) posterior alongside the frequentist
    # wins/total estimator. These theorems cover the posterior
    # itself; integration with Gate 2 is a follow-on slice.
    "posteriorMean_bounded": {
        "gate": "learning",
        "file": "Veritas/Learning/Reliability.lean",
        "status": "proven",
        "statement_natural_language":
            "The posterior mean of a Beta(α+successes, β+failures) "
            "distribution is in [0, 1] whenever the prior parameters "
            "are non-negative and their sum is strictly positive.",
        "axioms_used": [],
    },
    "posteriorMean_monotone_in_successes": {
        "gate": "learning",
        "file": "Veritas/Learning/Reliability.lean",
        "status": "proven",
        "statement_natural_language":
            "Adding successes (Nat k) to a BetaPosterior never decreases "
            "its posterior mean. The Bayesian analogue of "
            "reliabilityUpdate_monotone_on_wins, but unconditional — no "
            "'total > 0' premise is needed because the prior keeps the "
            "denominator positive even at zero observations.",
        "axioms_used": [],
    },
    "posteriorMean_uniform_prior_empty": {
        "gate": "learning",
        "file": "Veritas/Learning/Reliability.lean",
        "status": "proven",
        "statement_natural_language":
            "The uniform prior Beta(1, 1) with no observations yields "
            "posterior mean 1/2 — the canonical 'no evidence' state. "
            "Matches reliabilityScore's zero-sample fallback, so "
            "dropping BetaPosterior into Gate 2 preserves the "
            "zero-observation behavior.",
        "axioms_used": [],
    },
    # ── Gate-layer soundness contracts ─────────────────────────────
    # These are first-class theorems in Veritas/Gates/*.lean; they
    # document what each gate's Approve / Resize verdict *means*
    # independent of the underlying Finance / Strategy layer.
    "verifySignal_approve_implies_consistent": {
        "gate": 1,
        "file": "Veritas/Gates/SignalGate.lean",
        "status": "proven",
        "statement_natural_language":
            "If Gate 1 approves a proposal, then (1) at least one strategy "
            "in the policy registry fires on the submitted context, "
            "(2) all firing strategies are mutually consistent on "
            "direction, (3) the proposal's direction matches them, and "
            "(4) the union of attached assumptions is non-empty.",
        "axioms_used": [],
    },
    "checkConstraints_approve_within_ceiling": {
        "gate": 2,
        "file": "Veritas/Gates/ConstraintGate.lean",
        "status": "proven",
        "statement_natural_language":
            "If Gate 2 approves a proposal, its notional is at most the "
            "reliability-adjusted ceiling computed by "
            "calculatePositionSize.",
        "axioms_used": [],
    },
    "checkConstraints_resize_respects_ceiling": {
        "gate": 2,
        "file": "Veritas/Gates/ConstraintGate.lean",
        "status": "proven",
        "statement_natural_language":
            "If Gate 2 resizes a proposal to notional n, then n is at most "
            "the reliability-adjusted ceiling.",
        "axioms_used": [],
    },
    "checkConstraints_approve_implies_proposal_nonneg": {
        "gate": 2,
        "file": "Veritas/Gates/ConstraintGate.lean",
        "status": "proven",
        "statement_natural_language":
            "If Gate 2 approves a proposal, its notional is non-negative. "
            "Follows from Gate 2 rejecting on `p.notionalUsd ≤ 0`.",
        "axioms_used": [],
    },
    "checkConstraints_resize_nonneg": {
        "gate": 2,
        "file": "Veritas/Gates/ConstraintGate.lean",
        "status": "proven",
        "statement_natural_language":
            "If Gate 2 resizes a proposal, the resize value is non-negative. "
            "The Resize branch is past the `calculatePositionSize ≤ 0` "
            "rejection, so the resize value (which equals that quantity) "
            "is strictly positive.",
        "axioms_used": [],
    },
    "checkConstraints_resize_at_most_proposal": {
        "gate": 2,
        "file": "Veritas/Gates/ConstraintGate.lean",
        "status": "proven",
        "statement_natural_language":
            "If Gate 2 resizes a proposal to n, then n is at most the "
            "submitted proposal's notional. Together with "
            "checkConstraints_resize_respects_ceiling, witnesses that "
            "Gate 2 never inflates the caller's request.",
        "axioms_used": [],
    },
    "checkPortfolio_approve_respects_cap": {
        "gate": 3,
        "file": "Veritas/Gates/PortfolioGate.lean",
        "status": "proven",
        "statement_natural_language":
            "If Gate 3 approves a proposal, then the proposal's absolute "
            "notional added to the portfolio's correlation-adjusted "
            "exposure stays within the cap. Correlation weighting: "
            "same-asset positions count at 1.0, cross-asset positions "
            "count proportional to their |correlation| coefficient "
            "(0.0 when unknown).",
        "axioms_used": [],
    },
    "checkPortfolio_approve_respects_var_bound": {
        "gate": 3,
        "file": "Veritas/Gates/PortfolioGate.lean",
        "status": "proven",
        "statement_natural_language":
            "When the caller sets a positive dailyVarLimit, any Gate 3 "
            "Approve implies the portfolio's proposal-axis projected-"
            "exposure bound (portfolioVarBound: |notional|·volatility, "
            "weighted for existing positions by their absolute "
            "correlation with the proposal's asset, plus the proposal "
            "itself) stays within that limit. NOTE: portfolioVarBound "
            "is NOT in general an upper bound on full-portfolio "
            "√xᵀΣx — it does not consult correlations among existing "
            "positions. dailyVarLimit bounds the projected exposure "
            "along the proposal's asset direction. See "
            "docs/var-audit-2026-04-23.md for scope-of-validity "
            "analysis.",
        "axioms_used": [],
    },
    "checkPortfolio_resize_at_most_nonneg_proposal": {
        "gate": 3,
        "file": "Veritas/Gates/PortfolioGate.lean",
        "status": "proven",
        "statement_natural_language":
            "When the submitted proposal's notional is non-negative, any "
            "Gate 3 Resize value is at most that notional. Gate 3 only "
            "Resizes when the correlation-adjusted exposure plus "
            "|notional| exceeds the cap, which implies the resize value "
            "(cap minus adjusted exposure) is strictly below |notional|. "
            "Witnesses that Gate 3 never inflates the proposal it "
            "received from Gate 2.",
        "axioms_used": [],
    },
    "checkPortfolio_resize_respects_cap": {
        "gate": 3,
        "file": "Veritas/Gates/PortfolioGate.lean",
        "status": "proven",
        "statement_natural_language":
            "If Gate 3 resizes a proposal to m, then the correlation-"
            "adjusted exposure plus |m| stays within the cap. In the "
            "Resize branch m equals cap minus adjusted exposure and the "
            "branch's guard ensures that difference is positive, so "
            "|m| = m and adjusted + m exactly equals cap. Twin of "
            "checkPortfolio_approve_respects_cap for the Resize path.",
        "axioms_used": [],
    },
    "checkPortfolio_resize_nonneg": {
        "gate": 3,
        "file": "Veritas/Gates/PortfolioGate.lean",
        "status": "proven",
        "statement_natural_language":
            "If Gate 3 resizes a proposal to m, then m is strictly "
            "positive. The Resize branch is past the "
            "`cap − adjusted ≤ 0` rejection and the resize value equals "
            "`cap − adjusted`.",
        "axioms_used": [],
    },
    "checkPortfolio_resize_respects_var_bound": {
        "gate": 3,
        "file": "Veritas/Gates/PortfolioGate.lean",
        "status": "proven",
        "statement_natural_language":
            "If Gate 3 resizes a proposal and the caller set a positive "
            "dailyVarLimit, then the input proposal's proposal-axis "
            "projected-exposure bound (portfolioVarBound) stays within "
            "the limit. The VaR guard precedes the Resize branch in the "
            "dispatch chain, so by the time we reach Resize the guard "
            "must not have fired. Twin of "
            "checkPortfolio_approve_respects_var_bound for the Resize "
            "path. Same semantics caveat: the bound is on projected "
            "exposure along the proposal's asset, not on full-portfolio "
            "√xᵀΣx.",
        "axioms_used": [],
    },
    "portfolioVarBound_mono_in_abs_notional": {
        "gate": 3,
        "file": "Veritas/Gates/PortfolioGate.lean",
        "status": "proven",
        "statement_natural_language":
            "portfolioVarBound is monotone in |p.notionalUsd| when "
            "volatility is non-negative. Because the existing-positions "
            "contribution depends only on p.asset (preserved by struct "
            "update) and the proposal's contribution is "
            "|notional|·volatility, tighter |notional| tightens the bound "
            "whenever volatility ≥ 0. Lets the certificate-level VaR "
            "theorem carry a Gate-3-input bound down to the final "
            "(possibly resized) notional.",
        "axioms_used": [],
    },
    "certificate_soundness": {
        "gate": "combined",
        "file": "Veritas/Gates/Certificate.lean",
        "status": "proven",
        "statement_natural_language":
            "If a certificate emitted for a proposal approves, then Gate 1 "
            "found the proposal signal-consistent, Gate 2's verdict is "
            "not a rejection, and Gate 3's verdict is not a rejection. "
            "Numeric bounds for Gates 2 and 3 follow from their per-gate "
            "theorems.",
        "axioms_used": [],
    },
    "certificate_approve_final_within_gate2_ceiling": {
        "gate": "combined",
        "file": "Veritas/Gates/Certificate.lean",
        "status": "proven",
        "statement_natural_language":
            "If an emitted certificate approves, its finalNotionalUsd is "
            "at most the Gate-2 reliability-adjusted ceiling. Strengthens "
            "certificate_soundness with a numeric bound: Gate 3's possible "
            "downstream resize can only shrink Gate 2's output, never "
            "widen it, so the Gate-2 ceiling dominates every Approve path "
            "through the three-gate composition.",
        "axioms_used": [],
    },
    "certificate_approve_final_within_gate3_cap": {
        "gate": "combined",
        "file": "Veritas/Gates/Certificate.lean",
        "status": "proven",
        "statement_natural_language":
            "If an emitted certificate approves, the portfolio's "
            "correlation-adjusted exposure plus the absolute value of "
            "finalNotionalUsd stays within the cap. Twin of "
            "certificate_approve_final_within_gate2_ceiling for Gate 3's "
            "correlation-weighted exposure bound: every Approve path "
            "respects BOTH the Gate-2 Kelly ceiling AND the Gate-3 cap "
            "simultaneously.",
        "axioms_used": [],
    },
    "certificate_approve_final_within_gate3_var_bound": {
        "gate": "combined",
        "file": "Veritas/Gates/Certificate.lean",
        "status": "proven",
        "statement_natural_language":
            "When the caller opts into projected-exposure gating "
            "(dailyVarLimit > 0) and the proposal's volatility is "
            "non-negative, any approving certificate guarantees the "
            "portfolio's projected-exposure bound (portfolioVarBound) "
            "evaluated at finalNotionalUsd stays within the limit. "
            "Completes the three-gate composed-soundness story: every "
            "Approve path respects the Gate-2 Kelly ceiling, the "
            "Gate-3 gross-exposure cap, AND (when enabled) the Gate-3 "
            "projected-exposure bound, all simultaneously. Semantics "
            "caveat: see portfolioVarBound's entry and "
            "docs/var-audit-2026-04-23.md — the bound is on projected "
            "exposure along the proposal's asset direction, not on "
            "full-portfolio √xᵀΣx.",
        "axioms_used": [],
    },
}


# ── Pinning (v0.3 Slice 5) ─────────────────────────────────────────

def theorem_registry_canonical_bytes() -> bytes:
    """Canonical JSON encoding of the registry used for hashing.

    Keys are sorted; entry fields are sorted; separators are tight;
    UTF-8 encoded. This is the exact byte stream whose sha256 appears
    as ``theorem_registry_sha`` on the verifier's public endpoints."""
    return json.dumps(
        THEOREMS,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def compute_theorem_registry_sha() -> str:
    """Hex sha256 of ``theorem_registry_canonical_bytes()``.

    Callers pin this value (alongside ``build_sha``) at trust-setup
    time: the build sha identifies which Lean kernel produces verdicts,
    and the registry sha identifies which theorem list that build is
    claiming to prove. The two together commit Veritas's trust
    surface to a single hash-pinned snapshot."""
    return hashlib.sha256(theorem_registry_canonical_bytes()).hexdigest()
