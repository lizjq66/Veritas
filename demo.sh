#!/usr/bin/env bash
set -e

# Activate venv if it exists
[ -f .venv/bin/activate ] && source .venv/bin/activate

CORE=".lake/build/bin/veritas-core"

if [ ! -f "$CORE" ]; then
    echo "veritas-core not found. Run ./setup.sh first."
    exit 1
fi

echo "Veritas v0.1 — Gate verification demo"
echo "======================================"
echo ""

# Gate 2 demo: position sizing constraints
echo "Gate 2: Strategy-constraint compatibility"
echo "------------------------------------------"
echo ""

echo "Signal: SHORT BTC, funding rate -0.08%/hr (extreme)"
SIGNAL=$($CORE decide -0.0008 68000 0)
echo "  decide  -> $SIGNAL"
echo ""

echo "Sizing at different reliability levels:"
echo ""

# Exploration phase (sample_size < 10)
SIZE_EXPLORE=$($CORE size 10000 0.5 3)
echo "  Exploration (3 trades):   $SIZE_EXPLORE"

# No edge (reliability = 0.5, post-exploration)
SIZE_NO_EDGE=$($CORE size 10000 0.5 15)
echo "  No edge (50% reliable):  $SIZE_NO_EDGE"

# Moderate edge
SIZE_MODERATE=$($CORE size 10000 0.7 15)
echo "  Moderate (70% reliable): $SIZE_MODERATE"

# High reliability — hits 25% cap
SIZE_HIGH=$($CORE size 10000 0.95 15)
echo "  High (95% reliable):     $SIZE_HIGH"

echo ""
echo "Theorem guarantees (verified by Lean, not tested):"
echo "  positionSize_nonneg ............. all sizes >= 0     [proved]"
echo "  positionSize_capped ............. all sizes <= 25%   [proved]"
echo "  positionSize_zero_at_no_edge .... 50% -> size = 0   [proved]"
echo "  positionSize_monotone ........... 70% < 95% in size [proved]"
echo "  positionSize_explorationCapped .. first 10 = 1%     [proved]"
echo ""

echo "Gate pass: signal with 70% reliability -> \$2000 position (Kelly-sized)"
echo "Gate fail: signal with 50% reliability -> \$0 position (no edge, blocked)"
echo ""

echo "No signal scenario:"
NO_SIGNAL=$($CORE decide 0.0001 68000 0)
echo "  Funding 0.01%/hr (normal): $NO_SIGNAL"
echo "  Gate 1 blocks: funding below threshold, no signal generated"
echo ""

echo "Exit reason exhaustiveness:"
echo "  Every exit must be: assumption_met | assumption_broke | stop_loss"
echo "  exitReason_exhaustive theorem: [proved]"
echo ""

echo "Full loop test (24 trades on fake market):"
python -m pytest tests/test_loop.py::test_full_loop_deterministic -q 2>&1 | tail -3
echo ""
echo "Inspect: sqlite3 tests/demo_output/journal.db \"SELECT id, direction, exit_reason, regime_tag, signal_correct FROM trades LIMIT 5\""
