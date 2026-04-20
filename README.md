<div align="center">

# Veritas

A Lean-backed pre-trade verifier for AI trading agents.
One HTTP call between your agent's intent and the exchange.

[![license](https://img.shields.io/badge/license-Apache_2.0-blue.svg)](LICENSE)
[![release](https://img.shields.io/badge/release-v0.1-green)](https://github.com/lizjq66/Veritas/releases)
[![Lean](https://img.shields.io/badge/Lean-4.29-orange)](lean-toolchain)
[![python](https://img.shields.io/badge/python-3.11+-blue)](pyproject.toml)
[![tests](https://img.shields.io/badge/tests-86%20passing-brightgreen)](tests/)

</div>

---

## What is Veritas?

Veritas sits between your trading agent and the exchange. Your agent produces a `TradeProposal`; Veritas runs it through **three gates** and returns a structured certificate.

| Gate | Question |
|---|---|
| **1. Signal consistency** | Does the proposal agree with the declared policy? Are assumptions attached? |
| **2. Constraint compatibility** | Does the size fit the reliability-adjusted ceiling? |
| **3. Portfolio interference** | Does it clash with existing positions or breach the exposure cap? |

Gate logic is written in Lean 4 with closed proofs. Python is transport only.

Veritas is **not** a trading bot. It has no market view, no loop, no strategy. It is infrastructure — the same call works for a LangGraph node, a Claude tool-use agent, or a shell script hitting `curl`.

## Quick start

```bash
./setup.sh && lake build && pip install -r requirements.txt
python -m python.api.run        # starts the verifier on :8000
open http://localhost:8000      # interactive playground
```

Or straight from a terminal:

```bash
curl -sX POST http://localhost:8000/verify/proposal \
  -H 'Content-Type: application/json' \
  -d '{"proposal":    {"direction":"LONG","notional_usd":1500,"funding_rate":0.0012,"price":68000},
       "constraints": {"equity":10000,"reliability":0.8,"sample_size":20}}'
```

```json
{
  "gate1": {"verdict": "approve"},
  "gate2": {"verdict": "approve"},
  "gate3": {"verdict": "approve"},
  "approves": true,
  "final_notional_usd": 1500.0
}
```

## Docs

- **[`docs/PRODUCT_BRIEF.md`](docs/PRODUCT_BRIEF.md)** — what v0.1 ships, gate contracts, out-of-scope items
- **[`docs/POSITION_PAPER.md`](docs/POSITION_PAPER.md)** — why a verifier is the right product boundary
- **[`examples/external_integration/`](examples/external_integration/)** — Anthropic SDK + LangGraph working demos
- **[`CLAUDE.md`](CLAUDE.md)** — contributor guide

---

<div align="center">
Apache 2.0 · Built on Lean 4 · <a href="http://localhost:8000">localhost:8000</a> once running
</div>
