# Veritas

**Formally verified trading decisions. Lean 4 core, Python I/O shell, assumption-first architecture.**

A trading agent whose sizing, exit logic, and learning rules are Lean 4 theorems — not Python if/else. The Lean core compiles to a native binary; Python only handles I/O. Any claim Veritas makes about its behavior is backed by a proof or an explicit axiom, never by "trust me."

```
$ ./veritas-core size 10000 0.75 15
{ "position_size": 2500.000000, "equity": 10000.000000, "reliability": 0.750000 }
```

## What it looks like running

```
Veritas v0.1 | Lean-native core | BTC-USDC perp
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Core: veritas-core (Lean 4, compiled to native)
Proven theorems: 9/9 | Sorry count: 0 | Axioms: 20

[12:03:01] observe → funding=-0.000800, price=$68,000
[12:03:01] decide  → SHORT                              ← Lean core
[12:03:01] declare → "funding_rate_reverts_within_8h"    ← explicit assumption
[12:03:01] check   → reliability 50% (0/0)
[12:03:01] size    → $100.00 of $10,000                  ← exploration phase (1%)
[12:03:01] execute → SHORT 0.001471 BTC @ $68,000

[12:03:04] observe → funding=-0.000050, price=$67,900
[12:03:04] exit    → assumption_met (pnl +0.15%)         ← categorized exit
[12:03:04] learn   → reliability 0/0 → 1/1 (100%)       ← library updated
```

Every decision comes from the compiled Lean binary. Python passes data in, reads the decision out, and talks to Hyperliquid. `grep -rE "if.*(Signal|ExitDecision|PositionSize)" python/` returns nothing.

## Quick Start

```bash
git clone https://github.com/lizjq66/Veritas && cd Veritas

# Build the Lean core (requires elan — https://github.com/leanprover/elan)
lake build                            # compiles veritas-core binary

# Run with fake market data (no API keys needed)
pip install -r requirements.txt
python -m pytest tests/test_loop.py -v

# See the results
cat tests/demo_output/summary.md      # 24 trades, reliability evolution
sqlite3 tests/demo_output/journal.db "SELECT * FROM trades LIMIT 5"
```

To see it live with a dashboard:

```bash
VERITAS_LIVE_MODE=1 python -m python.api.run
# Open http://localhost:8000 — watch trades happen in real time
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Python I/O Shell                                            │
│                                                             │
│   observer.py ── Hyperliquid API ──┐                        │
│   executor.py ── order placement ──┤   No decision logic.   │
│   journal.py ─── SQLite read/write │   Python passes data   │
│   bridge.py ──── subprocess call ──┘   to Lean and back.    │
│        │                                                    │
│        │ subprocess + CLI args                              │
│        ▼                                                    │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Lean 4 Verified Core (veritas-core binary)              │ │
│ │                                                         │ │
│ │   Types.lean ─────── Direction, Signal, Assumption      │ │
│ │   PositionSizing ─── Kelly sizer + 5 theorems           │ │
│ │   ExitLogic ──────── 3-way exit + exhaustiveness proof  │ │
│ │   Reliability ────── Bayesian update + 2 theorems       │ │
│ │   FundingReversion ─ strategy (decide + extract)        │ │
│ │   Main.lean ──────── CLI dispatch                       │ │
│ │                                                         │ │
│ │   9 theorems proved. 0 sorry. 20 Float axioms.          │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│ Observation layer (read-only, no mutation):                  │
│   REST API ── /state, /assumptions, /trades, /verify        │
│   Dashboard ─ real-time SSE at http://localhost:8000         │
│   MCP Server ─ Claude/LLM agents query Veritas as a tool    │
└─────────────────────────────────────────────────────────────┘
```

**Trust boundary**: the Lean binary is the only trusted component. Python is treated as adversarial. Veritas's safety claims apply to the Lean side only. The observation layer (API, dashboard, MCP) is physically read-only — a middleware rejects any non-GET request with 405.

## What the theorems guarantee

| Theorem | Guarantee |
|---------|-----------|
| `positionSize_nonneg` | Position size is never negative |
| `positionSize_capped` | Position never exceeds 25% of equity |
| `positionSize_zero_at_no_edge` | Zero position when reliability ≤ 50% |
| `positionSize_monotone_in_reliability` | Higher reliability = larger position |
| `positionSize_explorationCapped` | First 10 trades use fixed 1% sizing |
| `kellyFraction_nonneg` | Kelly fraction is non-negative |
| `exitReason_exhaustive` | Every exit classified: met / broke / stop_loss |
| `reliabilityUpdate_monotone_on_wins` | Consecutive wins never decrease reliability |
| `reliabilityUpdate_bounded` | Reliability stays in [0, 1] |

All proofs depend on 20 axioms about IEEE 754 `Float` arithmetic in [`FloatAxioms.lean`](Veritas/Finance/FloatAxioms.lean). 13 are exact (ordering, sign). 7 are rounding-dependent (arithmetic monotonicity) — sound for Veritas's numerical ranges but not universally true. The axiom list is the honest boundary of what we prove vs. what we assume.

## Three Gates

Veritas's trust model has three verification gates. v0.1 implements one completely:

| Gate | What it checks | v0.1 status |
|------|---------------|-------------|
| **Gate 2: Strategy-constraint compatibility** | Position sizing and exit logic satisfy formal bounds regardless of input | **Complete** — 5 proven theorems |
| Gate 1: Signal consistency | Multiple signals don't contradict each other | Partial — single strategy, degenerates to threshold check |
| Gate 3: Portfolio interference | Adding a position keeps total risk in bounds | Not started — requires multi-strategy (v0.2) |

## MCP: Veritas as a tool for other agents

Any MCP-compatible LLM (Claude desktop, Claude Code) can query Veritas:

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

Available tools: `get_state`, `list_assumptions`, `get_assumption`, `get_recent_trades`, `verify_theorem`, `would_take_signal`.

The killer tool is `would_take_signal` — ask Veritas "if I wanted to short BTC, what would you say?" and get back a verified, formally-grounded opinion with sizing and reliability data.

## Limitations (honest)

**The fake market is too optimistic.** The built-in `FakeObserver` cycles through a fixed 6-step pattern where funding always reverts. This produces 100% win rate and never exercises `assumption_broke` or `stop_loss` paths. The mechanism works, but the demo data doesn't stress-test it. Real markets will produce 60-80% reliability at best.

**Hyperliquid testnet not yet connected end-to-end.** `observer.py` and `executor.py` have real API implementations (tested individually against testnet), but the full loop has not run against live testnet data yet. The integration is blocked on testnet wallet setup, not code.

**Sample size is tiny.** The assumption library has one assumption with at most 24 data points from the fake market. Bayesian reliability estimation is meaningless at n=24. Real statistical significance requires hundreds of trades.

**Float axioms are a pragmatic gap.** 7 of 20 axioms assume IEEE 754 rounding doesn't reverse inequalities. This is true for Veritas's numerical ranges but not provable in Lean today. When Lean/Mathlib ships a `Float` proof library, these should be replaced.

**Single strategy, single asset.** v0.1 only trades BTC-USDC funding rate reversion on Hyperliquid. Gate 1 and Gate 3 are architecturally defined but require a second strategy to activate.

**No LLM integration yet.** `extractor.py` is a stub. v0.1 hardcodes assumption extraction in Lean. Dynamic LLM-driven extraction is v0.2 scope — the LLM will be an untrusted oracle, with Lean validating its outputs.

## Project structure

```
Veritas/                    # Lean 4 source (750 lines)
  Types.lean, Finance/, Strategy/, Learning/, Main.lean

python/                     # Python I/O shell (~800 lines)
  main.py, observer.py, executor.py, journal.py, bridge.py

python/api/                 # REST API + dashboard (~600 lines)
  server.py, routes/, static/index.html, events.py, live_runner.py

python/mcp/                 # MCP server (~260 lines)
  server.py, __main__.py

tests/                      # 55 tests, all passing
  test_loop.py, test_api_*.py, test_sse.py, test_mcp_server.py
  demo_output/              # committed test artifacts (journal.db, summary.md)
```

## License

MIT
