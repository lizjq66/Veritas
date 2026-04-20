# Veritas

> **A pre-trade verifier for trading agents.** One HTTP call between your agent's intent and the exchange. Three gates. A structured certificate. Gate logic is written in Lean 4.

```
  your agent    ──▶    POST /verify/proposal    ──▶    Certificate
  (any framework)                                      ├─ gate1: approve | resize | reject
                                                       ├─ gate2: ...
                                                       ├─ gate3: ...
                                                       ├─ assumptions: [...]
                                                       ├─ final_notional_usd: ...
                                                       └─ approves: true | false
```

Veritas is for **AI agents**, not humans. It has no UI-as-product, no trading loop, no opinion on the market. It sits between whatever you are (LangGraph node, Claude tool-use, in-house policy engine) and the exchange, and forces every proposed trade through three gates before capital moves.

---

## The three gates

| # | Gate | Question | Output |
|---|---|---|---|
| 1 | **Signal consistency** | Does the proposal agree with the declared policy? Are assumptions attached? | `approve` (with assumptions) / `reject` |
| 2 | **Strategy-constraint compatibility** | Does the size fit the reliability-adjusted ceiling? | `approve` / `resize` (to ceiling) / `reject` |
| 3 | **Portfolio interference** | Does it clash with existing positions or breach the gross-exposure cap? | `approve` / `resize` (to headroom) / `reject` |

All three execute in Lean; each carries its own soundness theorem ([`Veritas/Gates/*.lean`](Veritas/Gates/)). Python cannot mint an approval that did not come from the kernel — a CI invariant ([`tests/test_bypass_invariant.py`](tests/test_bypass_invariant.py)) enforces it.

---

## Try it in 30 seconds

```bash
./setup.sh && lake build && pip install -r requirements.txt
python -m python.api.run           # starts the verifier on :8000
open http://localhost:8000         # interactive playground
```

The playground lets you POST a proposal, see each gate's verdict colour-coded, and inspect the raw certificate JSON. Preset scenarios cover clean approval, direction conflict, oversize resize, no-edge rejection, and portfolio conflict.

Or straight from the command line:

```bash
curl -sX POST http://localhost:8000/verify/proposal \
  -H 'Content-Type: application/json' \
  -d '{
    "proposal":    {"direction":"LONG","notional_usd":1500,"funding_rate":0.0012,"price":68000},
    "constraints": {"equity":10000,"reliability":0.8,"sample_size":20}
  }' | python -m json.tool
```

```json
{
  "gate1": {"verdict": "approve"},
  "gate2": {"verdict": "approve"},
  "gate3": {"verdict": "approve"},
  "assumptions": [{"name": "funding_rate_reverts_within_8h", "description": "..."}],
  "final_notional_usd": 1500.0,
  "approves": true
}
```

---

## Integration surfaces

Same contract, three transports:

| Transport | Entry point | Use when |
|---|---|---|
| **HTTP** | `POST /verify/proposal` | any language, any framework |
| **Python** | `python.verifier.Verifier().verify(...)` | in-process Python callers |
| **MCP** | `verify_proposal` tool | Claude Desktop, Claude Code, any MCP agent |
| **CLI** | `veritas-core emit-certificate ...` | shell scripts, tests, CI |

Working examples under [`examples/external_integration/`](examples/external_integration/):

- [`anthropic_sdk_loop.py`](examples/external_integration/anthropic_sdk_loop.py) — Claude produces a structured `TradeProposal` via tool-use; the script POSTs it to Veritas.
- [`langgraph_integration.py`](examples/external_integration/langgraph_integration.py) — a LangGraph state graph with `intent → propose → verify → execute|rejected`, where verification is a `@tool`.

---

## Architecture

```
                calling agent (NOT Veritas)
                           │
                  TradeProposal + constraints + portfolio
                           │
                           ▼
    ┌────────────────────────────────────────────────────┐
    │  Python transport/adapters  (untrusted)            │
    │    python/verifier.py   ·  canonical entry point   │
    │    python/bridge.py     ·  JSON bridge to kernel   │
    │    python/api/          ·  FastAPI + playground    │
    │    python/mcp/          ·  MCP server              │
    └────────────────────────────────────────────────────┘
                           │  subprocess + JSON
                           ▼
    ┌────────────────────────────────────────────────────┐
    │  Lean 4 verification kernel  (trusted)             │
    │    Gates/SignalGate.lean      ·  Gate 1 + theorem  │
    │    Gates/ConstraintGate.lean  ·  Gate 2 + theorems │
    │    Gates/PortfolioGate.lean   ·  Gate 3 + theorem  │
    │    Gates/Certificate.lean     ·  combined          │
    │    Finance/PositionSizing     ·  5 theorems        │
    │    Strategy/ExitLogic         ·  exhaustiveness    │
    │    Learning/Reliability       ·  bounded, monotone │
    └────────────────────────────────────────────────────┘
                           │
                           ▼
                     Certificate
```

- **Lean is trusted.** All gate decisions live here. Pure functions, type-level invariants, theorems.
- **Python is untrusted.** Network, DB, HTTP, subprocess, adapter glue. A compromise here cannot make Veritas approve a trade the kernel rejected — there is no code path for it.
- **Observation layer is read-only.** `GET /state`, `/assumptions`, `/trades`, `/verify/theorem/{name}` never mutate. `POST` is allowed only on `/verify/*`.

---

## What v0.1 verifies

Each Gate ships its own soundness theorem; all proofs are closed.

| Theorem | File | Status |
|---|---|---|
| `verifySignal_approve_implies_consistent` | `Gates/SignalGate.lean` | ✅ proven |
| `checkConstraints_approve_within_ceiling` | `Gates/ConstraintGate.lean` | ✅ proven |
| `checkConstraints_resize_respects_ceiling` | `Gates/ConstraintGate.lean` | ✅ proven |
| `checkPortfolio_approve_respects_cap` | `Gates/PortfolioGate.lean` | ✅ proven |
| `certificate_soundness` | `Gates/Certificate.lean` | ✅ proven |
| `positionSize_nonneg` / `_capped` / `_zero_at_no_edge` / `_monotone_in_reliability` / `_explorationCapped` | `Finance/PositionSizing.lean` | ✅ proven (×5) |
| `kellyFraction_nonneg` / `_mono` | `Finance/Kelly.lean` | ✅ proven (×2) |
| `exitReason_exhaustive` | `Strategy/ExitLogic.lean` | ✅ proven |
| `reliabilityUpdate_monotone_on_wins` / `_bounded` | `Learning/Reliability.lean` | ✅ proven (×2) |

**Sorry count: 0. Axiom count: 20** (all in `Finance/FloatAxioms.lean`; 13 exact + 7 rounding-dependent, classified at the file header). Reducing rounding-dependent axioms by migrating decision paths to `Rat`/`Real` is a v0.2 goal.

Veritas does **not** verify: correctness of the caller's alpha, correctness of the bundled funding-reversion policy, anything about a specific execution venue, anything the caller does after the certificate is issued. Those are the caller's problem.

---

## v0.1 ship criterion

v0.1 ships when the verifier API contract holds against fixture proposals — **not** when an adapter executes real trades. The bundled `HyperliquidObserver` / `HyperliquidExecutor` are reference integrations only, not on the critical path. See [`docs/PRODUCT_BRIEF.md`](docs/PRODUCT_BRIEF.md#v01-completion-criteria).

---

## The bundled example runner

For readers who want to see a concrete caller, the repo ships a funding-reversion trading agent that talks to the Veritas verifier on every tick:

```bash
python -m python.main          # fake market + fake executor
python -m python.main --live   # Hyperliquid testnet (example adapter)
```

This runner is **not the product**. It is a demonstration of what sits *above* Veritas. Dashboard lives at [`http://localhost:8000/runner`](http://localhost:8000/runner).

---

## Project structure

```
Veritas/
├── Veritas/                        # Lean verification kernel
│   ├── Gates/                      #   — Gate 1/2/3 + Certificate + Types
│   ├── Finance/                    #   — PositionSizing, Kelly, MaxLoss, ExecutionQuality, FloatAxioms
│   ├── Strategy/                   #   — FundingReversion, ExitLogic, Regime
│   ├── Learning/                   #   — Reliability update + theorems
│   ├── Types.lean                  #   — shared sum types
│   └── Main.lean                   #   — CLI dispatcher
├── python/
│   ├── verifier.py                 # canonical verifier entry point
│   ├── schemas.py                  # TradeProposal, Constraints, Portfolio, Verdict, Certificate
│   ├── bridge.py                   # JSON bridge to veritas-core
│   ├── api/                        # FastAPI + playground (static/index.html)
│   ├── mcp/                        # MCP server
│   ├── observer.py / executor.py   # example Hyperliquid adapters
│   ├── journal.py                  # example runner's SQLite journal
│   └── main.py                     # example funding-reversion runner
├── examples/external_integration/  # working LangGraph + Anthropic SDK demos
├── tests/                          # pytest suite (86 tests, 0 mocks on kernel)
├── docs/                           # PRODUCT_BRIEF, POSITION_PAPER
└── demo.sh                         # CLI gate walkthrough
```

---

## Lean CLI surface

```
veritas-core verify-signal      <dir> <fr> <price> <ts> <oi> <notional>
veritas-core check-constraints  <dir> <notional> <equity> <rel> <n>
                                <max_lev> <max_pos_frac> <stop_pct>
veritas-core check-portfolio    <dir> <notional> <equity> <max_gross_frac>
                                (none | one <dir> <ep> <sz>)
veritas-core emit-certificate   <all-of-the-above-concatenated>
veritas-core classify-exit      (alias for `monitor`)
```

Primitive commands (`decide`, `extract`, `size`, `monitor`, `update-reliability`, `classify-regime`, `build-context`, `judge-signal`, `execution-quality`) remain as building blocks for adapters.

---

## License

Apache 2.0. See [LICENSE](LICENSE).
