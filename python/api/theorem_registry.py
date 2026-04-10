"""Hardcoded theorem registry for the /verify endpoint.

v0.1: static lookup. v0.3 will parse Lean source and generate this
from the actual proof state.
"""

from __future__ import annotations

THEOREMS: dict[str, dict] = {
    "positionSize_nonneg": {
        "file": "Veritas/Finance/PositionSizing.lean",
        "status": "sorry",
        "statement_natural_language": "Post-exploration position size is always non-negative",
        "axioms_used": ["Float.le_refl", "Float.mul_nonneg"],
    },
    "positionSize_capped": {
        "file": "Veritas/Finance/PositionSizing.lean",
        "status": "sorry",
        "statement_natural_language": "Post-exploration position size never exceeds 25% of equity",
        "axioms_used": ["Float.mul_nonneg", "Float.le_of_not_gt"],
    },
    "positionSize_monotone_in_reliability": {
        "file": "Veritas/Finance/PositionSizing.lean",
        "status": "sorry",
        "statement_natural_language": "Higher reliability produces larger position size (monotone)",
        "axioms_used": ["kellyFraction_mono", "Float.mul_le_mul_of_nonneg_left"],
    },
    "positionSize_zero_at_no_edge": {
        "file": "Veritas/Finance/PositionSizing.lean",
        "status": "proven",
        "statement_natural_language": "Post-exploration position is zero when reliability is 0.5 or below",
        "axioms_used": [],
    },
    "positionSize_explorationCapped": {
        "file": "Veritas/Finance/PositionSizing.lean",
        "status": "proven",
        "statement_natural_language": "During exploration phase, position is fixed at 1% of equity",
        "axioms_used": [],
    },
    "kellyFraction_nonneg": {
        "file": "Veritas/Finance/Kelly.lean",
        "status": "proven",
        "statement_natural_language": "Kelly fraction is always non-negative",
        "axioms_used": ["Float.le_refl", "Float.zero_point_zero_eq", "Float.not_le_to_ge"],
    },
    "kellyFraction_mono": {
        "file": "Veritas/Finance/Kelly.lean",
        "status": "axiom",
        "statement_natural_language": "Kelly fraction is monotone in win probability",
        "axioms_used": [],
    },
    "exitReason_exhaustive": {
        "file": "Veritas/Strategy/ExitLogic.lean",
        "status": "proven",
        "statement_natural_language": "Every exit is classified into exactly one of three reasons",
        "axioms_used": [],
    },
    "reliabilityUpdate_monotone_on_wins": {
        "file": "Veritas/Learning/Reliability.lean",
        "status": "proven",
        "statement_natural_language": "After a win, reliability never decreases",
        "axioms_used": ["Float.div_succ_mono"],
    },
    "reliabilityUpdate_bounded": {
        "file": "Veritas/Learning/Reliability.lean",
        "status": "proven",
        "statement_natural_language": "Reliability is always in [0, 1]",
        "axioms_used": ["Float.div_nonneg", "Float.div_le_one", "Float.Nat_toFloat_nonneg", "Float.Nat_toFloat_pos"],
    },
}
