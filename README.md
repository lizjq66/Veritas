<div align="center">

<img src="docs/assets/veritas.svg" width="96" alt="Veritas">

# Veritas

A Lean-backed pre-trade verifier for AI trading agents.
One HTTP call between your agent's intent and the exchange.

[![paper](https://img.shields.io/badge/paper-LaTeX-red)](docs/paper/veritas.tex)
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

Veritas is **not** a trading bot. It has no market view, no loop, no strategy, and no connection to any exchange. You bring the venue; Veritas returns the verdict. The same call works for a LangGraph node, a Claude tool-use agent, or a shell script hitting `curl`.

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
  "final_notional_usd": 1500.0,
  "attestation": {
    "schema_version": 2,
    "build_sha": "...", "public_key": "...", "signature": "...",
    "request_digest": "..."
  }
}
```

## Using Veritas as a caller

Every returned certificate is signed. Your agent fetches Veritas's public key and build hash once (trust-on-first-use), then independently verifies every verdict against those pins without having to trust the operator.

```python
from python.sdk import (
    TradeProposal, AccountConstraints, Portfolio,
    Certificate, compute_request_digest,
    verify_certificate, AttestationError,
)

# One-time: pin what your ops team approved.
PINNED_PUBLIC_KEY = "..."       # GET /verify/pubkey → public_key
PINNED_BUILD_SHA  = "..."       # GET /verify/pubkey → build_sha

# Per-call: build request, submit, verify.
proposal     = TradeProposal(direction="LONG", notional_usd=1500.0,
                             funding_rate=0.0012, price=68000.0, timestamp=0)
constraints  = AccountConstraints(equity=10000.0, reliability=0.8, sample_size=20)
portfolio    = Portfolio()

cert = Certificate.from_json(http_post("/verify/proposal", ...))

digest = compute_request_digest(proposal, constraints, portfolio)
try:
    verify_certificate(
        cert.body_json(), cert.attestation,
        expected_public_key=PINNED_PUBLIC_KEY,
        expected_request_digest=digest,   # replay protection
    )
except AttestationError as e:
    raise SystemExit(f"Untrusted Veritas response: {e}")

if cert.attestation.build_sha != PINNED_BUILD_SHA:
    raise SystemExit("Veritas build drifted from the pinned kernel.")

if cert.approves:
    submit_order(cert.final_notional_usd)
```

The SDK surface (`python/sdk.py`) is deliberately `veritas-core`-free — no Lean binary, no subprocess, zero dependency on the verifier side. An agent that only talks to Veritas over HTTP or MCP does not need to install or run the Lean kernel locally.

## Docs

- **[`docs/paper/veritas.tex`](docs/paper/veritas.tex)** — paper (LaTeX, `make` to build PDF)
- **[`docs/PRODUCT_BRIEF.md`](docs/PRODUCT_BRIEF.md)** — what v0.1 ships, gate contracts, out-of-scope items
- **[`docs/POSITION_PAPER.md`](docs/POSITION_PAPER.md)** — prose companion to the paper
- **[`examples/external_integration/`](examples/external_integration/)** — Anthropic SDK + LangGraph working demos
- **[`CLAUDE.md`](CLAUDE.md)** — contributor guide

---

<div align="center">
Apache 2.0 · Built on Lean 4 · <a href="http://localhost:8000">localhost:8000</a> once running
</div>
