<div align="center">

<img src="docs/assets/veritas.svg" width="96" alt="Veritas">

# Veritas

A Lean-backed pre-trade verifier for AI trading agents.
One HTTP call between your agent's intent and the exchange.

[![paper](https://img.shields.io/badge/paper-LaTeX-red)](docs/paper/veritas.tex)
[![license](https://img.shields.io/badge/license-Apache_2.0-blue.svg)](LICENSE)
[![release](https://img.shields.io/badge/release-v0.4-green)](https://github.com/lizjq66/Veritas/releases)
[![Lean](https://img.shields.io/badge/Lean-4.29-orange)](lean-toolchain)
[![python](https://img.shields.io/badge/python-3.11+-blue)](pyproject.toml)
[![tests](https://img.shields.io/badge/tests-176%20passing-brightgreen)](tests/)

</div>

---

## What is Veritas?

Veritas sits between your trading agent and the exchange. Your agent produces a `TradeProposal`; Veritas runs it through **three gates** and returns a cryptographically signed certificate.

| Gate | Question |
|---|---|
| **1. Signal consistency** | Does the proposal agree with a declared policy? Are assumptions attached? |
| **2. Constraint compatibility** | Does the size fit the reliability-adjusted ceiling? (Bayesian posterior over wins / losses; half-Kelly; hard-capped at 25% of equity.) |
| **3. Portfolio interference** | Does it clash with existing positions, breach the correlation-weighted exposure cap, or exceed the projected-exposure VaR limit? |

Gate logic is written in Lean 4 with closed proofs (38 theorems, 0 `sorry`, 0 Veritas-declared axioms). Python is transport only.

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
       "constraints": {"equity":10000,"successes":16,"failures":4}}'
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
    "build_sha": "…",
    "public_key": "…",
    "signature": "…",
    "request_digest": "…"
  }
}
```

## Using Veritas as a caller

Every returned certificate is cryptographically signed. An agent that knows which `veritas-core` build it trusts can **verify each verdict independently**, without trusting the operator.

### 1. Trust setup (once, at onboarding)

Fetch `/verify/pubkey` and pin three values:

```python
trust = requests.get("http://localhost:8000/verify/pubkey").json()

PINNED_PUBLIC_KEY           = trust["public_key"]             # who signs
PINNED_BUILD_SHA            = trust["build_sha"]              # which Lean kernel
PINNED_THEOREM_REGISTRY_SHA = trust["theorem_registry_sha"]   # which claims
```

Your ops team reviews the build, reads the theorem list (`GET /verify/theorems`), and decides to trust. Any future drift shows up on the next `/verify/pubkey` fetch and is a re-review trigger — never a silent upgrade.

### 2. Per-call verification

```python
from python.sdk import (
    TradeProposal, AccountConstraints, Portfolio,
    Certificate, compute_request_digest,
    verify_certificate, AttestationError,
)

proposal    = TradeProposal(direction="LONG", notional_usd=1500.0,
                            funding_rate=0.0012, price=68000.0, timestamp=0)
constraints = AccountConstraints(equity=10000.0, successes=16, failures=4)
portfolio   = Portfolio()

cert = Certificate.from_json(http_post("/verify/proposal", ...))

# (a) signature + input-binding (blocks tampering and cross-request replay)
digest = compute_request_digest(proposal, constraints, portfolio)
try:
    verify_certificate(
        cert.body_json(), cert.attestation,
        expected_public_key=PINNED_PUBLIC_KEY,
        expected_request_digest=digest,
    )
except AttestationError as e:
    raise SystemExit(f"Untrusted Veritas response: {e}")

# (b) kernel-drift (blocks silent Lean rebuild on the operator side)
if cert.attestation.build_sha != PINNED_BUILD_SHA:
    raise SystemExit("Veritas build drifted from the pinned kernel.")

if cert.approves:
    submit_order(cert.final_notional_usd)
```

### What each pin protects against

| Pin | Blocks |
|---|---|
| `public_key` | Another signer impersonating Veritas — even with a syntactically valid-looking cert |
| `build_sha` | Silent operator-side kernel swap (new Lean build → possibly different gate semantics) |
| `theorem_registry_sha` | The operator narrowing or rewording Veritas's trust claims between your reviews |
| `request_digest` | Replay of a verdict issued for a different proposal (same signer, same kernel, different input) |

### The SDK is Lean-binary-free

`python/sdk.py` has no `subprocess`, no `veritas-core` binary dependency, no Lean toolchain. An agent that only talks to Veritas over HTTP or MCP can import the caller surface without building or running the Lean kernel locally. A CI-enforced invariant (`test_sdk_import_does_not_pull_in_bridge`) keeps that surface clean.

### Input semantics — Bayesian reliability (v0.4+)

`AccountConstraints` takes observed `successes` / `failures` on the proposal's assumption, plus optional Beta prior `(prior_alpha, prior_beta)`. Defaults are `Beta(1, 1)` (Laplace smoothing). Cold start (`0, 0`) reads as posterior mean `1/2` and stays in the exploration phase — byte-identical to v0.3's frequentist cold start, but small-sample sizing is now more conservative.

Legacy `reliability` / `sample_size` fields are still accepted on the HTTP wire with a one-shot `DeprecationWarning`; **they are removed in v0.5** (see [`CHANGELOG.md`](CHANGELOG.md)).

### `dailyVarLimit` semantics (fixed commitment)

Gate 3's optional VaR check bounds a **proposal-axis projected exposure**, not full-portfolio 1-day stddev `√xᵀΣx`. Two existing positions that are mutually correlated but each uncorrelated with the proposal's asset contribute `0` to `portfolioVarBound` while still carrying real portfolio variance.

This is the committed semantic of `dailyVarLimit`. Full-portfolio `√xᵀΣx` gating, if ever added, ships as a separate constraint field and a separate gate branch — never by redefining `dailyVarLimit`. See [`docs/var-audit-2026-04-23.md`](docs/var-audit-2026-04-23.md) for counter-examples and the full scope-of-validity analysis.

## Docs

- **[`CHANGELOG.md`](CHANGELOG.md)** — caller-visible changes per release, with migration guidance
- **[`docs/paper/veritas.tex`](docs/paper/veritas.tex)** — paper (LaTeX, `make` to build PDF)
- **[`docs/PRODUCT_BRIEF.md`](docs/PRODUCT_BRIEF.md)** — what v0.1 ships, gate contracts, out-of-scope items
- **[`docs/POSITION_PAPER.md`](docs/POSITION_PAPER.md)** — prose companion to the paper
- **[`docs/var-audit-2026-04-23.md`](docs/var-audit-2026-04-23.md)** — `portfolioVarBound` scope analysis
- **[`docs/migration-plan-2026-04-23.md`](docs/migration-plan-2026-04-23.md)** — v0.4 Bayesian migration plan
- **[`examples/external_integration/`](examples/external_integration/)** — Anthropic SDK + LangGraph working demos
- **[`CLAUDE.md`](CLAUDE.md)** — contributor guide

---

<div align="center">
Apache 2.0 · Built on Lean 4 · <a href="http://localhost:8000">localhost:8000</a> once running
</div>
