#!/usr/bin/env bash
set -e

echo "Veritas setup"
echo "============="

# Check for elan/lean
if ! command -v elan &>/dev/null; then
    echo "elan not found. Install it from https://github.com/leanprover/elan"
    echo "  curl https://elan.lean-lang.org/elan-init.sh -sSf | sh"
    exit 1
fi

echo "[1/3] Building Lean core (this may take a few minutes on first run)..."
lake build 2>&1 | tail -3

echo "[2/3] Setting up Python environment..."
python3 -m venv .venv 2>/dev/null || true
source .venv/bin/activate
pip install -r requirements.txt -q 2>&1 | tail -1

echo "[3/3] Verifying..."
.lake/build/bin/veritas-core version

echo ""
echo "Setup complete. Run ./demo.sh to see Veritas in action."
