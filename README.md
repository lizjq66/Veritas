# Veritas

Every serious AI-driven trading firm runs a model risk control function — a committee that decides whether an ML model is trustworthy enough to touch real capital. This function is typically internal, manual, and opaque.

Veritas makes it a piece of open-source infrastructure. A trading agent where every decision must pass a Lean 4 proof before execution, and where the trust claims are themselves machine-checkable.

## Quick Start

```bash
git clone https://github.com/lizjq66/Veritas && cd Veritas
./setup.sh        # builds Lean core, installs Python deps
./demo.sh         # runs a signal through all gates, shows pass/fail
```

Output:

```
Gate 2: Strategy-constraint compatibility
------------------------------------------

Sizing at different reliability levels:

  Exploration (3 trades):   { "position_size": 100.00 ... }    <- fixed 1%
  No edge (50% reliable):   { "position_size": 0.00 ... }      <- BLOCKED
  Moderate (70% reliable):  { "position_size": 2000.00 ... }   <- Kelly-sized
  High (95% reliable):      { "position_size": 2500.00 ... }   <- 25% cap

Gate pass: 70% reliability -> $2000 position
Gate fail: 50% reliability -> $0 position (no edge, Lean returns zero)
```

## Architecture

```
                    UNVERIFIED                          VERIFIED
                    (Python, probabilistic)             (Lean 4, deterministic)

  Hyperliquid  ─→  observer.py                    ┌─────────────────────────────┐
  API               │                             │                             │
                    │ MarketSnapshot (JSON)        │  Gate 1: Signal consistency │
                    │                             │  - contradicting signals?   │
                    ▼                             │                             │
               ┌─────────┐   subprocess    ┌────→│  Gate 2: Constraints        │
               │ bridge.py│ ─────────────→ │     │  - size ≥ 0        [proved] │
               └─────────┘                 │     │  - size ≤ 25%      [proved] │
                    │                      │     │  - no edge → zero  [proved] │
                    │                      │     │  - exit exhaustive [proved] │
                    │         veritas-core  │     │                             │
                    │         (native bin)  │     │  Gate 3: Portfolio risk     │
                    │                      │     │  - total exposure ≤ limit   │
                    ▼                      │     │                             │
               executor.py  ←─────────────┘     └─────────────────────────────┘
                    │          PositionSize                     │
                    │          (typed, bounded)                 │
                    ▼                                           │
               Hyperliquid                          Assumption Library
               Testnet                              (SQLite, feeds reliability
                                                     into Gate 2 sizing)
```

There is no function in the codebase that takes an unverified signal and produces an order. The path from market data to execution passes through the compiled Lean binary. This separation is enforced at compile time by the type system, not at runtime by validation checks.

`grep -rE "if.*(Signal|ExitDecision|PositionSize)" python/` returns nothing. Python has zero decision logic.

## Why Lean 4?

Most ML trading systems achieve trustworthiness through engineering discipline: pinned dependencies, fixed random seeds, snapshotted data, containerized environments, extensive backtests. These are best-effort guarantees. They degrade under regime changes, silent library updates, and long-tail edge cases.

Veritas achieves trustworthiness through the type system. A signal that fails Gate 1/2/3 verification cannot be executed — not because we catch it at runtime, but because the architecture does not compile a path from unverified signal to order. Reproducibility is not a property we maintain. It is a property that cannot be violated.

## What the theorems guarantee

| Theorem | Guarantee | Status |
|---------|-----------|--------|
| `positionSize_nonneg` | Position size is never negative | proved |
| `positionSize_capped` | Position never exceeds 25% of equity | proved |
| `positionSize_zero_at_no_edge` | Zero position when reliability ≤ 50% | proved |
| `positionSize_monotone_in_reliability` | Higher reliability = larger position | proved |
| `positionSize_explorationCapped` | First 10 trades use fixed 1% sizing | proved |
| `kellyFraction_nonneg` | Kelly fraction is non-negative | proved |
| `exitReason_exhaustive` | Every exit classified: met / broke / stop_loss | proved |
| `reliabilityUpdate_monotone_on_wins` | Consecutive wins never decrease reliability | proved |
| `reliabilityUpdate_bounded` | Reliability stays in [0, 1] | proved |

All proofs depend on 20 axioms about IEEE 754 `Float` arithmetic in [`FloatAxioms.lean`](Veritas/Finance/FloatAxioms.lean). 13 are exact (ordering, sign). 7 are rounding-dependent (arithmetic monotonicity) — sound for Veritas's numerical ranges but not universally true for all IEEE 754 inputs. The axiom list is the honest boundary of what we prove vs. what we assume.

## Three Gates

| Gate | What it verifies | v0.1 status |
|------|-----------------|-------------|
| **Gate 2: Strategy-constraint compatibility** | Position sizing and exit logic satisfy formal bounds regardless of input | **Complete** — 5 proven theorems |
| Gate 1: Signal consistency | Multiple signals don't contradict each other | Partial — single strategy, degenerates to threshold check |
| Gate 3: Portfolio interference | Adding a position keeps total risk in bounds | Not started — requires multi-strategy (v0.2) |

## Reliability decomposition

Each trial records rich context (8 market features + regime tag) and decomposes outcomes into signal accuracy vs. execution quality:

```
trial = {
  signal_correct: bool,              # did the market move as predicted?
  execution_quality: {
    slippage_bps, fill_delay_ms,     # did execution capture the edge?
    realized_vs_expected_pnl
  },
  context: {
    funding_rate, asset_price,       # what was the market state?
    open_interest, volume_24h,
    premium, spread_bps,
    regime_tag: bull | bear | choppy
  },
  source: mock | testnet | mainnet   # where did this data come from?
}
```

This schema supports regime-conditional reliability and time-decayed reliability (architected, not yet enabled — waiting for testnet data).

## Current status (April 2026)

- Trial schema supports decomposing reliability into signal accuracy, execution quality, and regime-specific performance. Currently populated with 24 mock trials; Hyperliquid testnet integration in progress.
- Reliability is currently tracked as a single scalar per assumption. Regime-conditional reliability (2.1) and time-decayed reliability (2.2) are architected in the schema and will be enabled once testnet data starts flowing.
- Reliability half-life defaults are placeholders awaiting empirical calibration. The architecture permits recalibration without reproving any Lean theorems.
- Gate 2 currently evaluates a small number of strategy constraints. The constraint library will grow based on real-world deployment feedback.
- The MCP interface exposes read and verification endpoints only. Veritas gives opinions; execution is the caller's responsibility. This is a design decision, not a temporary limitation.

## MCP: Veritas as a tool for other agents

Any MCP-compatible LLM (Claude Desktop, Claude Code) can query Veritas as a trust oracle:

```json
{
  "mcpServers": {
    "veritas": {
      "command": "python",
      "args": ["-m", "python.mcp"],
      "cwd": "/path/to/Veritas",
      "env": { "VERITAS_DB_PATH": "/path/to/Veritas/data/veritas.db" }
    }
  }
}
```

Tools: `get_state`, `list_assumptions`, `get_assumption`, `get_recent_trades`, `verify_theorem`, `would_take_signal`.

`would_take_signal` is the core interface: an external agent submits a trade direction, Veritas returns whether its gates would pass the signal, what position size the Lean sizer would output, and the reliability data backing the decision.

## Observation layer

```bash
# REST API + real-time dashboard
VERITAS_DB_PATH=tests/demo_output/journal.db python -m python.api.run
# Open http://localhost:8000
```

Six read-only endpoints (`/state`, `/assumptions`, `/trades`, `/verify`, `/stream/events`, `/health`). SSE event stream for real-time updates. Single-file vanilla JS dashboard. Read-only middleware rejects any non-GET request with 405.

## Project structure

```
Veritas/                    # Lean 4 verified core (~750 lines)
  Types.lean, Finance/, Strategy/, Learning/, Main.lean

python/                     # Python I/O shell (~800 lines)
  main.py, observer.py, executor.py, journal.py, bridge.py, regime.py

python/api/                 # REST API + dashboard (~600 lines)
python/mcp/                 # MCP server (~260 lines)
tests/                      # 52+ tests, all passing
  demo_output/              # committed artifacts (journal.db, summary.md)
```

## License

Apache 2.0
