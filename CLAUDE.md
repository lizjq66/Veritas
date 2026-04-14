# Veritas — Claude Code Instructions

## Language policy

All pure functions (no I/O) go in Lean. Python is restricted to:
- Network calls (Hyperliquid API, HTTP server)
- Database operations (SQLite)
- Framework code (FastAPI, MCP, uvicorn)
- Subprocess bridge to veritas-core

If you find yourself writing a computation in Python that doesn't
touch network/DB/filesystem, stop — it belongs in Lean. Add a new
command to veritas-core and call it via bridge.py.

## Trust boundary

Lean core is trusted. Python is untrusted. All safety claims apply
to the Lean side only. The observation layer (API, dashboard, MCP)
is physically read-only.

## Decision logic invariant

Python must contain zero decision logic. Verify with:
```
grep -rE "if.*(Signal|ExitDecision|PositionSize)" python/
```
This must return nothing. If it does, move the logic to Lean.

## Build

```
lake build          # Lean core → .lake/build/bin/veritas-core
pip install -r requirements.txt   # Python deps
```

## Test

```
python -m pytest tests/ -v
```

## Source tagging

Trades are tagged `mock`, `testnet`, or `mainnet`. Never mix sources
in reliability calculations without explicit filtering.
