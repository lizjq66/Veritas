# Veritas — Claude Code Instructions

## What Veritas is

Veritas is a **pre-trade verifier**, not an autonomous trading agent.
A calling trading agent submits a proposed trade; Veritas runs it
through three gates (signal consistency, constraint compatibility,
portfolio interference) and returns a structured certificate.

The product surface is:

- `python/verifier.py` — canonical Python entry point (`Verifier.verify(...)`)
- `python/api/routes/verify.py` — HTTP surface (`POST /verify/proposal`)
- `python/mcp/server.py` — MCP tool (`verify_proposal`)
- `.lake/build/bin/veritas-core` — Lean CLI (`verify-signal`,
  `check-constraints`, `check-portfolio`, `classify-exit`,
  `emit-certificate`)

Everything else — `python/main.py`, `observer.py`, `executor.py`,
`journal.py`, the dashboard, the MCP `get_runner_state` / trade-history
tools — is an **example runner** that demonstrates a caller wiring
itself to Veritas. When touching that code, preserve the distinction:
the product is the verifier, the runner is a demo.

## Language policy

All pure functions go in Lean. That includes every gate decision, every
size calculation, every exit classification, every reliability update.

Python is restricted to:

- Transport (FastAPI, MCP, uvicorn)
- Persistence for the example runner (SQLite via `journal.py`)
- Adapters for specific venues (`observer.py`, `executor.py`)
- The subprocess + JSON bridge to `veritas-core`

If you find yourself writing a computation in Python that doesn't
touch network/DB/HTTP/subprocess, stop. It belongs in Lean. Add a
command to `veritas-core` and call it from `bridge.py`.

## Trust boundary

Lean is trusted. Python is untrusted. All safety claims apply to the
Lean side only. The observation layer (`GET` endpoints, dashboard, MCP
inspection tools) is physically read-only; the verification layer
(`POST /verify/*`) is a pure function from request to kernel response.

**Python must never approve a trade without flowing through the Lean
gates.** There is no Python-side fallback, no cache, no fast-path. If
an adapter reimplements a verdict, that is a bug — push the logic to
Lean and re-expose it via the bridge.

## Invariants enforced by CI

`tests/test_bypass_invariant.py` fails the build if:

- Python reintroduces decision branching on `Signal`, `ExitDecision`,
  or `PositionSize` — `grep -rnE "if.*(Signal|ExitDecision|PositionSize)" python/`
  must return nothing.
- Python mints `Verdict(tag="approve"|"reject"|"resize"` outside
  `python/schemas.py` or `python/verifier.py`.
- Any module other than `python/bridge.py` invokes `veritas-core`
  directly via `subprocess.run` / `subprocess.Popen`.

`tests/test_gates.py` and `tests/test_loop.py` exercise the full gate
stack against the real compiled kernel — there is no mocking of the
verifier.

## Build

```
lake build                     # Lean kernel → .lake/build/bin/veritas-core
pip install -r requirements.txt
```

Optional extras:

```
pip install -e .[hyperliquid]  # adapters for the bundled example runner
pip install -e .[dev]          # pytest, pytest-asyncio, httpx
```

## Test

```
python -m pytest tests/ -v
```

## Where to add new features

- A new **gate check** → new function in `Veritas/Gates/*.lean`,
  wired into `Veritas.Main`, re-exported via `python/bridge.py` and
  `python/verifier.py`, covered in `tests/test_gates.py`.
- A new **policy** (e.g. basis arbitrage) → new file under
  `Veritas/Strategy/`, referenced from `verifySignal`, assumptions
  declared via `extractAssumptions`.
- A new **venue adapter** → a sibling to `observer.py` / `executor.py`.
  Observes and executes only; never branches on Veritas types.

Exchange integrations, runners, dashboards, and journals are
**secondary adapters**, not the product core. Keep them demotable.

## Source tagging

The bundled example runner tags its trades `mock`, `testnet`, or
`mainnet`. Never mix sources in reliability calculations without
explicit filtering.

## v0.1 ship criterion

v0.1 ships when the verifier API contract holds against fixture
proposals — not when an adapter has executed real trades. Concretely:
`tests/test_gates.py`, `tests/test_api_endpoints.py`,
`tests/test_mcp_server.py`, and `tests/test_bypass_invariant.py` all
pass; `lake build` produces a sorry-free binary. Whether
`HyperliquidObserver` / `HyperliquidExecutor` have been exercised
against real testnet traffic is explicitly a v0.2+ concern and does
not gate the v0.1 release.
