# Veritas

**A trading agent on Hyperliquid whose decision logic is written in Lean 4.**

Veritas watches perpetual funding rates on Hyperliquid, and when its assumptions about the market fire, it takes a position. The parts that decide *whether* to trade — signal detection, sizing, max-loss bounds, reliability tracking — are written in Lean 4, not Python. Python handles I/O: market data, order execution, logging, API surfaces.

The separation is architectural, not stylistic. Python code cannot bypass the Lean decision layer. Every live trade goes through a proof obligation first.

## How it works

```
Hyperliquid market data  -->  observer (Python)  -->  Veritas decision core (Lean 4)
                                                              |
                                                     +--------+--------+
                                                     |                 |
                                            Strategy evaluates   Finance computes
                                            signal + regime      sizing + max loss
                                                     |                 |
                                                     +--------+--------+
                                                              |
                                              Learning updates reliability
                                                              |
                                                              v
                                                  executor (Python) --> Hyperliquid
                                                              |
                                                  journal (SQLite) logs every event
```

### The Lean layer

- **`Veritas/Strategy/`** — the actual trading hypotheses.
  - `FundingReversion.lean` — when funding rate deviates, it tends to revert within N hours.
  - `Regime.lean` — bull/bear/choppy classification; gates which assumptions apply.
  - `ExitLogic.lean` — when an open position must be closed.
- **`Veritas/Finance/`** — position-level math.
  - `Kelly.lean`, `PositionSizing.lean` — how large a position is allowed given reliability and capital.
  - `MaxLoss.lean` — bounded loss per trade; enforced at the type level.
  - `ExecutionQuality.lean` — slippage and fill-delay accounting, separated from signal correctness.
  - `FloatAxioms.lean` — the numerical axioms the above depend on.
- **`Veritas/Learning/Reliability.lean`** — tracks each assumption's empirical reliability per regime, decomposed across signal accuracy vs execution quality.

### The Python layer

- **`python/observer.py`** — pulls funding rates, prices, open interest from Hyperliquid.
- **`python/extractor.py`** — turns raw market data into the structured context the Lean layer consumes.
- **`python/bridge.py`** — the call boundary between Python and the Lean decision core.
- **`python/executor.py`** — sends signed orders to Hyperliquid when a decision is approved.
- **`python/journal.py`** — appends every event (signal, decision, fill, outcome) to SQLite.
- **`python/api/`** — read-only REST API exposing state, assumptions, recent trades.
- **`python/mcp/`** — MCP server exposing the same state to agent frameworks (Claude Desktop, Claude Code, etc).
- **`python/main.py`** — the live loop entry point.

## Why Lean 4

Decision logic written in Python can be bypassed by a logic bug, a missing `return`, a try/except that swallows a violation. Decision logic written in Lean 4 is type-checked by a kernel: once the proof obligations for a trade are discharged, the architecture does not compile a path to execution that skips them.

This matters specifically here because the decision surface is small but consequential. Whether to open a position, how large, under what assumption, with what max-loss bound — these five things decide whether the agent survives regime changes. They live in Lean, not Python.

The Lean code does zero IO. It cannot call APIs, read files, or reach the network. That invariant is enforced by Lean's import system at compile time, not by convention.

## Quick start

**Prerequisites:** [Lean 4](https://leanprover.github.io/lean4/doc/setup.html), Python 3.9+, a Hyperliquid testnet account if you want to run live.

```bash
# 1. Install
./setup.sh

# 2. Build Lean
lake build

# 3. Run against a simulated fake market (no real orders)
source .venv/bin/activate
python -m python.main

# 4. Run on Hyperliquid testnet
python -m python.main --live
```

Configuration lives in `config.example.toml`. Copy it to `config.toml` and fill in your Hyperliquid testnet keys before running `--live`.

### What you'll see

The live loop prints each decision:

```
[tick] funding_rate=0.0012 regime=bull
  └─ assumption: funding_rate_reverts_within_8h (reliability 83% in bull, n=12)
  └─ Kelly sizing: $1,650 (capped at 25% equity)
  └─ max_loss_bound: 5%
  └─ decision: EXECUTE SHORT
```

Every tick, signal, decision, and fill is written to `data/veritas.db` (SQLite). Inspect with any SQLite viewer, or via the API.

### API

Start the API server:

```bash
python -m python.api
```

- `GET /state` — current phase, equity, open position
- `GET /assumptions` — reliability per assumption, broken down by regime
- `GET /trades?limit=N` — recent trade history

### MCP

The MCP server exposes the same read surface to agent frameworks:

```bash
python -m python.mcp
```

Compatible with Claude Desktop, Claude Code, and any MCP-compatible agent. Tools: `get_state`, `list_assumptions`, `get_assumption`, `get_recent_trades`, `verify_theorem`, `would_take_signal`.

## Project structure

```
Veritas/
├── Veritas/                    # Lean 4 decision core
│   ├── Strategy/               # Trading hypotheses
│   ├── Finance/                # Position sizing, max loss, execution quality
│   ├── Learning/               # Assumption reliability tracking
│   ├── Types.lean              # Shared type definitions
│   └── Main.lean
├── python/                     # I/O shell around the Lean core
│   ├── observer.py             # Hyperliquid market data
│   ├── extractor.py            # Raw data → structured context
│   ├── bridge.py               # Python ↔ Lean boundary
│   ├── executor.py             # Order execution
│   ├── journal.py              # Event logging to SQLite
│   ├── api/                    # REST API (read-only)
│   ├── mcp/                    # MCP server
│   └── main.py                 # Live loop entry point
├── tests/                      # Python test suite
├── data/                       # SQLite databases (gitignored)
├── logs/                       # Runtime logs (gitignored)
├── config.example.toml         # Copy to config.toml
├── lakefile.lean               # Lean build
└── setup.sh                    # One-shot install
```

## Current status (April 2026)

- Lean decision core: built and working.
- Simulated fake-market loop: working. Default `python -m python.main` runs this.
- Hyperliquid testnet integration: in place, behind the `--live` flag.
- Mainnet: not deployed. Do not point this at real funds.
- Assumption library: small. Currently `funding_rate_reverts_within_8h` is the primary assumption. More will be added based on testnet behavior.
- Reliability is tracked per assumption, per regime, with signal accuracy decomposed from execution quality. Time-decayed reliability is architected but not yet enabled — it turns on once there's enough testnet history.
- Half-life defaults in `Veritas/Learning/Reliability.lean` are placeholders pending empirical calibration.

## License

Apache 2.0. See [LICENSE](LICENSE).
