# Veritas

**A Lean-backed verification layer that sits between a trading agent and execution, forcing every proposed trade through three gates before capital is put at risk.**

Veritas is not the trading agent. It has no view on the market, no alpha, and no trading loop of its own. It is the thing a trading agent calls — once per proposed trade — to ask:

1. **Is this proposal internally coherent?** (*signal / assumption consistency*)
2. **Does it fit the account's policy envelope?** (*strategy-constraint compatibility*)
3. **Does it clash with the existing portfolio?** (*portfolio interference*)

In response, the caller gets a structured certificate: approve / resize / reject, with machine-readable reason codes and a list of attached assumptions. The gate logic is written in Lean 4. Python is transport.

## The three gates

### Gate 1 — signal consistency
Does the proposal agree with the policy Veritas publishes? In v0.1 the only bundled policy is funding-rate reversion on perps, so Gate 1 checks that the direction matches what that policy would emit under the submitted context, and attaches explicit assumptions when it does. On approval, the caller knows precisely *what they are betting on*. On rejection, the caller knows *why*: `no_signal_under_policy`, `direction_conflicts_with_signal`, `malformed_proposal_no_assumptions`.

### Gate 2 — strategy-constraint compatibility
Given the caller's equity, reliability score, and sample size, what is the largest notional a trade may carry? Gate 2 returns `approve` if the proposal fits, `resize` to the reliability-adjusted ceiling if it doesn't, and `reject` when no non-zero size is allowed (reliability below 0.5, zero edge). This gate is Veritas's strongest formal property: the ceiling it enforces is proved non-negative, capped at 25 % of equity, zero at no edge, monotone in reliability, and fixed at 1 % during the first ten trades of exploration.

### Gate 3 — portfolio interference
Given the caller's existing positions and the (possibly resized) proposal, does the combined exposure violate portfolio-wide constraints? v0.1 flags opposite-direction conflicts and resizes down when total gross notional would breach a configured cap.

All three gates execute in Lean. The Python API / MCP / bridge are transport only. If a caller talks to Veritas over any interface, the decision path is the same.

## What Veritas is and isn't

**Veritas is**

- A verifier — a function from `(proposal, constraints, portfolio)` to `certificate`.
- A policy firewall — no execution path can bypass the gates, because the gates are the only approval surface.
- A trust boundary — the kernel is pure Lean; anything that could compromise it lives outside.

**Veritas isn't**

- An autonomous trader. It has no loop, no scheduler, no market view.
- An alpha source. It does not invent strategies. The one bundled policy (funding-rate reversion) is an example.
- A Hyperliquid product. Hyperliquid is the example venue the bundled runner demonstrates on; adapters are pluggable.

## Architecture

```
                 trading agent (not Veritas)
                           │
                  TradeProposal + constraints + portfolio
                           │
                           ▼
    ┌────────────────────────────────────────────────────┐
    │   Veritas Python surface (adapters / transport)    │
    │     verifier.py   — canonical entry point           │
    │     bridge.py     — JSON bridge to Lean kernel      │
    │     api/          — FastAPI (POST /verify/...)      │
    │     mcp/          — MCP tool (verify_proposal)      │
    └────────────────────────────────────────────────────┘
                           │
                   subprocess + JSON
                           │
                           ▼
    ┌────────────────────────────────────────────────────┐
    │   Veritas Lean 4 verification kernel               │
    │     Gates/SignalGate.lean       — Gate 1            │
    │     Gates/ConstraintGate.lean   — Gate 2            │
    │     Gates/PortfolioGate.lean    — Gate 3            │
    │     Gates/Certificate.lean      — combined          │
    │     Finance/PositionSizing.lean — 5 theorems        │
    │     Strategy/ExitLogic.lean     — exhaustiveness    │
    │     Learning/Reliability.lean   — bounded, monotone │
    └────────────────────────────────────────────────────┘
                           │
                           ▼
                     Certificate
                (verdict × 3, assumptions, final notional)
```

The Lean kernel compiles to a native binary (`.lake/build/bin/veritas-core`) that exposes one CLI per gate. The Python layer never interprets a verdict — it forwards the kernel's output to the caller.

### The trust boundary

- **Lean is trusted.** All gate decisions live here. Pure functions, type-level invariants, theorems over position sizing and reliability.
- **Python is untrusted.** Network, DB, HTTP, subprocess management, adapter glue. A compromise here cannot make Veritas approve a trade the Lean kernel rejected; there is no code path for it.
- **The observation layer is read-only.** `GET /state`, `/assumptions`, `/trades`, `/verify/theorem/*` never mutate. `POST` is allowed only on `/verify/*` endpoints, which are pure functions over the kernel.

A CI-guarded grep (`tests/test_bypass_invariant.py`) fails if Python reintroduces decision logic, if any module mints `Verdict` values outside the schema layer, or if any module other than `python/bridge.py` invokes `veritas-core` directly.

## Quickstart — verifier mode

```bash
# 1. Install
./setup.sh            # elan + venv
lake build            # compile the Lean kernel → .lake/build/bin/veritas-core
pip install -r requirements.txt

# 2. Verify a proposed trade from Python
python -c "
from python.verifier import Verifier
from python.schemas import TradeProposal, AccountConstraints

v = Verifier()
cert = v.verify(
    TradeProposal(direction='LONG', notional_usd=1500.0,
                  funding_rate=0.0012, price=68000.0, timestamp=0),
    AccountConstraints(equity=10000.0, reliability=0.8, sample_size=20),
)
print(cert.approves, cert.final_notional_usd)
print(cert.gate1.tag, cert.gate2.tag, cert.gate3.tag)
"

# 3. Or run it as an HTTP service
python -m python.api.run
# POST /verify/proposal with a {proposal, constraints, portfolio?} body
```

Example HTTP request:

```bash
curl -s -X POST http://127.0.0.1:8000/verify/proposal \
  -H 'Content-Type: application/json' \
  -d '{
        "proposal":    {"direction":"LONG","notional_usd":1500,"funding_rate":0.0012,"price":68000},
        "constraints": {"equity":10000,"reliability":0.8,"sample_size":20}
      }' | python -m json.tool
```

Response:

```json
{
  "gate1": {"verdict": "approve"},
  "gate2": {"verdict": "approve"},
  "gate3": {"verdict": "approve"},
  "assumptions": [
    {"name": "funding_rate_reverts_within_8h", "description": "..."}
  ],
  "final_notional_usd": 1500.0,
  "approves": true
}
```

## End-to-end demo

```bash
./demo.sh
```

Walks a proposal through each gate and then the combined certificate. Also shows the failure modes: direction conflict at Gate 1, oversize resize at Gate 2, portfolio-conflict rejection at Gate 3.

## MCP mode

```bash
python -m python.mcp
```

Exposes Veritas as an MCP tool to Claude Desktop, Claude Code, or any MCP-compatible agent. The primary tool is `verify_proposal`. Inspection tools:

- `list_assumptions`, `get_assumption` — the assumption library
- `verify_theorem`, `list_theorems` — status of the underlying Lean theorems
- `get_runner_state`, `get_recent_trades` — state of the bundled demo runner

## The bundled example runner

For readers who want to see a concrete caller, the repo ships a funding-reversion trading agent that talks to the Veritas verifier on every tick:

```bash
python -m python.main          # fake market, fake executor (default)
python -m python.main --live   # Hyperliquid testnet — example adapter only
```

This runner is **not the product**. It is a demonstration of what sits *above* Veritas. The runner contains zero decision logic; every approve/resize/reject flows through the three gates.

The `--live` flag is an **optional demonstration**, not a v0.1 ship requirement. v0.1 is complete when the verifier API contract holds against fixture proposals — see [`docs/PRODUCT_BRIEF.md`](docs/PRODUCT_BRIEF.md#v01-completion-criteria). Exercising the Hyperliquid adapters against real testnet traffic is a v0.2+ concern.

## External agent integrations

Veritas is infrastructure — any agent framework can call `POST /verify/proposal` before executing. See [`examples/external_integration/`](examples/external_integration/) for two minimal working examples:

- **`anthropic_sdk_loop.py`** — Anthropic SDK tool-use: LLM proposes, Veritas verifies, caller decides.
- **`langgraph_integration.py`** — a four-node LangGraph agent that calls Veritas as a `@tool`, routing approvals to an execute node and rejections to a rejection handler.

Both are pure consumers of the HTTP contract and carry their own `requirements-examples.txt`.

## Project structure

```
Veritas/
├── Veritas/                        # Lean 4 verification kernel
│   ├── Gates/
│   │   ├── Types.lean              # TradeProposal, Verdict, Certificate
│   │   ├── SignalGate.lean         # Gate 1
│   │   ├── ConstraintGate.lean     # Gate 2
│   │   ├── PortfolioGate.lean      # Gate 3
│   │   └── Certificate.lean        # run all three, short-circuit on reject
│   ├── Finance/                    # PositionSizing + theorems, Kelly, MaxLoss
│   ├── Strategy/                   # FundingReversion, ExitLogic, Regime
│   ├── Learning/                   # Reliability update rule + theorems
│   ├── Types.lean                  # shared sum types (Direction, ExitReason, …)
│   └── Main.lean                   # CLI dispatcher
├── python/
│   ├── verifier.py                 # canonical verification surface
│   ├── schemas.py                  # TradeProposal / Constraints / Portfolio / Verdict / Certificate
│   ├── bridge.py                   # JSON bridge to veritas-core
│   ├── api/                        # FastAPI verification + observation layer
│   ├── mcp/                        # MCP server (verify_proposal + inspection)
│   ├── observer.py                 # example Hyperliquid observer (adapter)
│   ├── executor.py                 # example Hyperliquid executor (adapter)
│   ├── journal.py                  # example runner's SQLite journal
│   └── main.py                     # example runner (funding-reversion)
├── tests/                          # pytest suite (82 tests)
├── docs/
│   ├── PRODUCT_BRIEF.md
│   └── POSITION_PAPER.md
├── config.example.toml             # verifier + policy + adapter config
├── demo.sh                         # gate-walk demo
└── lakefile.lean
```

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

Primitive commands (`decide`, `extract`, `size`, `monitor`, `update-reliability`, `classify-regime`, `build-context`, `judge-signal`, `execution-quality`) remain available as building blocks for adapters and the bundled runner.

## What v0.1 verifies, and what it doesn't

Veritas publishes the following theorems:

| Theorem | Claim |
|---|---|
| `positionSize_nonneg` | post-exploration size ≥ 0 |
| `positionSize_capped` | post-exploration size ≤ 25 % of equity |
| `positionSize_zero_at_no_edge` | reliability ≤ 0.5 → size 0 |
| `positionSize_monotone_in_reliability` | higher reliability → not smaller |
| `positionSize_explorationCapped` | first 10 trades fixed at 1 % |
| `kellyFraction_nonneg`, `kellyFraction_mono` | Kelly is well-behaved |
| `exitReason_exhaustive` | every exit in {met, broke, stop} |
| `reliabilityUpdate_monotone_on_wins` | wins never reduce reliability |
| `reliabilityUpdate_bounded` | reliability ∈ [0, 1] |

Sorry count: **0**. Axiom count: **20**, all in `Veritas/Finance/FloatAxioms.lean` with soundness classification. Reducing the rounding-dependent axioms is a v0.2 goal.

Veritas does **not** verify: correctness of the caller's alpha, correctness of the funding-reversion policy, anything about a specific execution venue, or anything the caller does after the certificate is issued. Those are the caller's problems.

## License

Apache 2.0. See [LICENSE](LICENSE).
