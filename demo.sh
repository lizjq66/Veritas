#!/usr/bin/env bash
set -e

# Veritas demo — walk a proposed trade through the three gates and
# show what the verifier returns. This is the product: a proposal goes
# in, a certificate comes out.

[ -f .venv/bin/activate ] && source .venv/bin/activate

CORE=".lake/build/bin/veritas-core"
if [ ! -f "$CORE" ]; then
    echo "veritas-core not found. Run ./setup.sh first."
    exit 1
fi

hr() { printf '%s\n' '──────────────────────────────────────────────────────────────'; }

echo "Veritas v0.1 — pre-trade verifier demo"
hr
echo
echo "Scenario: a calling agent proposes LONG BTC, notional \$1,500,"
echo "at funding rate +0.12%/hr (positive → funding reverts down → LONG)."
echo "Account: \$10,000 equity, reliability 0.8 over 20 past trades."
echo "Portfolio: empty."
echo

# ── Gate 1 ────────────────────────────────────────────────────────
echo "[Gate 1] signal_consistency"
hr
$CORE verify-signal LONG 0.0012 68000 0 0 1500 | python -m json.tool
echo

# ── Gate 2 ────────────────────────────────────────────────────────
echo "[Gate 2] strategy_constraint_compatibility"
hr
$CORE check-constraints LONG 1500 10000 0.8 20 1.0 0.25 5.0 | python -m json.tool
echo

# ── Gate 3 ────────────────────────────────────────────────────────
echo "[Gate 3] portfolio_interference"
hr
$CORE check-portfolio LONG 1500 10000 0.50 none | python -m json.tool
echo

# ── Combined certificate ─────────────────────────────────────────
echo "[Certificate] full trace"
hr
$CORE emit-certificate LONG 1500 0.0012 68000 0 0 10000 0.8 20 1.0 0.25 5.0 0.50 none | python -m json.tool
echo

# ── Failure mode: direction conflict ─────────────────────────────
echo "Failure case: same LONG proposal on NEGATIVE funding."
echo "Policy would signal SHORT → Gate 1 rejects, certificate short-circuits."
hr
$CORE emit-certificate LONG 1500 -0.0008 68000 0 0 10000 0.8 20 1.0 0.25 5.0 0.50 none | python -m json.tool
echo

# ── Failure mode: oversize → gate 2 resize ───────────────────────
echo "Failure case: \$9,000 notional on \$10,000 equity, 90% reliability."
echo "Gate 2 resizes down to the reliability-adjusted ceiling."
hr
$CORE emit-certificate LONG 9000 0.0012 68000 0 0 10000 0.9 30 1.0 0.25 5.0 0.50 none | python -m json.tool
echo

# ── Failure mode: gate 3 direction conflict ──────────────────────
echo "Failure case: new LONG against an existing SHORT position."
echo "Gate 3 rejects on direction conflict."
hr
$CORE emit-certificate LONG 1000 0.0012 68000 0 0 10000 0.8 20 1.0 0.25 5.0 0.50 one SHORT 67500 0.03 | python -m json.tool
echo

# ── Theorem inventory ────────────────────────────────────────────
echo "Underlying theorems (proved by Lean, not checked at runtime)"
hr
echo "  Gate 2 bounds:"
echo "    positionSize_nonneg              — approved size ≥ 0"
echo "    positionSize_capped              — approved size ≤ 25% of equity"
echo "    positionSize_zero_at_no_edge     — reliability ≤ 0.5 → size 0"
echo "    positionSize_monotone_in_reliab  — higher reliability → not smaller"
echo "    positionSize_explorationCapped   — first 10 trades fixed at 1%"
echo "  Exit classification:"
echo "    exitReason_exhaustive            — every exit in {met, broke, stop}"
echo "  Reliability update:"
echo "    reliabilityUpdate_monotone_on_wins"
echo "    reliabilityUpdate_bounded        — reliability ∈ [0, 1]"
echo

# ── Optional: run the example agent loop ─────────────────────────
echo "Example runner: a demo trading agent calling the verifier."
hr
python -m pytest tests/test_loop.py::test_full_loop_deterministic -q 2>&1 | tail -3
echo
echo "Inspect the journal:"
echo "  sqlite3 tests/demo_output/journal.db \\"
echo "    \"SELECT id, direction, exit_reason, signal_correct FROM trades LIMIT 5\""
