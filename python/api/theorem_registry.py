"""Hardcoded theorem registry for the /verify/theorem endpoint.

v0.1: static lookup. A future version will parse Lean source and
generate this from the actual proof state.

Each entry names one theorem Veritas publishes as a trust signal:
its file, its proof status (proven / sorry / axiom), a natural-language
statement, and the axioms it depends on.
"""

from __future__ import annotations

THEOREMS: dict[str, dict] = {
    # ── Gate 2 bounds (Finance.PositionSizing) ────────────────────
    "positionSize_nonneg": {
        "gate": 2,
        "file": "Veritas/Finance/PositionSizing.lean",
        "status": "proven",
        "statement_natural_language":
            "Post-exploration position size is always non-negative.",
        "axioms_used": ["Float.le_refl", "Float.mul_nonneg"],
    },
    "positionSize_capped": {
        "gate": 2,
        "file": "Veritas/Finance/PositionSizing.lean",
        "status": "proven",
        "statement_natural_language":
            "Post-exploration position size never exceeds 25% of equity.",
        "axioms_used": ["Float.mul_nonneg", "Float.le_of_not_gt"],
    },
    "positionSize_monotone_in_reliability": {
        "gate": 2,
        "file": "Veritas/Finance/PositionSizing.lean",
        "status": "proven",
        "statement_natural_language":
            "Higher reliability never produces a smaller post-exploration position.",
        "axioms_used": ["kellyFraction_mono", "Float.mul_le_mul_of_nonneg_left"],
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
    # ── Kelly layer (Finance.Kelly) ──────────────────────────────
    "kellyFraction_nonneg": {
        "gate": 2,
        "file": "Veritas/Finance/Kelly.lean",
        "status": "proven",
        "statement_natural_language":
            "The Kelly fraction is always non-negative.",
        "axioms_used": ["Float.le_refl", "Float.zero_point_zero_eq",
                        "Float.not_le_to_ge"],
    },
    "kellyFraction_mono": {
        "gate": 2,
        "file": "Veritas/Finance/Kelly.lean",
        "status": "proven",
        "statement_natural_language":
            "The Kelly fraction is monotone in win probability.",
        "axioms_used": ["Float.mul_le_mul_of_nonneg_left", "Float.sub_le_sub_left",
                        "Float.sub_le_sub_right", "Float.div_le_div_of_nonneg_right"],
    },
    # ── Exit classification (Strategy.ExitLogic) ─────────────────
    "exitReason_exhaustive": {
        "gate": "classify_exit",
        "file": "Veritas/Strategy/ExitLogic.lean",
        "status": "proven",
        "statement_natural_language":
            "Every exit is classified into exactly one of three reasons "
            "(assumption_met | assumption_broke | stop_loss).",
        "axioms_used": [],
    },
    # ── Reliability update (Learning.Reliability) ────────────────
    "reliabilityUpdate_monotone_on_wins": {
        "gate": "learning",
        "file": "Veritas/Learning/Reliability.lean",
        "status": "proven",
        "statement_natural_language":
            "After a win, reliability never decreases.",
        "axioms_used": ["Float.div_succ_mono"],
    },
    "reliabilityUpdate_bounded": {
        "gate": "learning",
        "file": "Veritas/Learning/Reliability.lean",
        "status": "proven",
        "statement_natural_language":
            "Reliability is always in [0, 1].",
        "axioms_used": ["Float.div_nonneg", "Float.div_le_one",
                        "Float.Nat_toFloat_nonneg", "Float.Nat_toFloat_pos"],
    },
    # ── Gate-layer soundness contracts ─────────────────────────────
    # These are first-class theorems living in Veritas/Gates/*.lean.
    # They document what each gate's Approve/Resize verdict *means*,
    # independent of the underlying Finance/Strategy layer.
    "verifySignal_approve_implies_consistent": {
        "gate": 1,
        "file": "Veritas/Gates/SignalGate.lean",
        "status": "proven",
        "statement_natural_language":
            "If Gate 1 approves a proposal, then the proposal is "
            "signal-consistent: Veritas's own policy would emit a signal "
            "for the submitted context, its direction matches the "
            "proposal's, and at least one assumption is attached.",
        "axioms_used": [],
    },
    "checkConstraints_approve_within_ceiling": {
        "gate": 2,
        "file": "Veritas/Gates/ConstraintGate.lean",
        "status": "proven",
        "statement_natural_language":
            "If Gate 2 approves a proposal, its notional is at most the "
            "reliability-adjusted ceiling computed by calculatePositionSize.",
        "axioms_used": [],
    },
    "checkConstraints_resize_respects_ceiling": {
        "gate": 2,
        "file": "Veritas/Gates/ConstraintGate.lean",
        "status": "proven",
        "statement_natural_language":
            "If Gate 2 resizes a proposal to notional n, then n is at most "
            "the reliability-adjusted ceiling.",
        "axioms_used": ["Float.le_refl"],
    },
    "checkPortfolio_approve_respects_cap": {
        "gate": 3,
        "file": "Veritas/Gates/PortfolioGate.lean",
        "status": "proven",
        "statement_natural_language":
            "If Gate 3 approves a proposal, then adding its absolute "
            "notional to existing gross notional stays within the "
            "portfolio's gross-exposure cap.",
        "axioms_used": [],
    },
    "certificate_soundness": {
        "gate": "combined",
        "file": "Veritas/Gates/Certificate.lean",
        "status": "proven",
        "statement_natural_language":
            "If a certificate emitted for a proposal approves, then Gate 1 "
            "found the proposal signal-consistent, Gate 2's verdict is not "
            "a rejection, and Gate 3's verdict is not a rejection. Numeric "
            "bounds for Gates 2 and 3 follow from their per-gate theorems.",
        "axioms_used": [],
    },
}
