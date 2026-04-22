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

**Veritas is agent-facing infrastructure. The caller brings venue
connectivity, price feeds, and execution; Veritas returns the
verdict.** The bundled Hyperliquid observer and executor exist only
to make "what a caller's integration looks like" concrete — they are
example tooling, not product surface. No release milestone gates on
their behavior against a live venue, testnet or otherwise. The
intended entry points for new callers are `examples/external_integration/`
(Anthropic SDK, LangGraph), not `observer.py` / `executor.py`.

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

Lean is trusted. Python is untrusted *for decisions*. All safety
claims apply to the Lean side only. The observation layer (`GET`
endpoints, dashboard, MCP inspection tools) is physically read-only;
the verification layer (`POST /verify/*`) is a pure function from
request to kernel response.

**Python must never approve a trade without flowing through the Lean
gates.** There is no Python-side fallback, no cache, no fast-path. If
an adapter reimplements a verdict, that is a bug — push the logic to
Lean and re-expose it via the bridge.

### Python as provenance anchor (v0.3 slice 3+)

Python is additionally trusted as a *provenance* signer: the Ed25519
key used to sign `Attestation`s lives in the Python process
(`python/attestation.py`), and each signature asserts "this verdict
was produced by the `veritas-core` binary whose sha256 is
`build_sha`". This does not relax the decision-trust boundary — the
bypass-invariant tests still enforce that Python cannot mint a verdict
of its own. A malicious Python operator *could* in principle sign a
verdict that disagrees with what Lean returned; defeating that attack
requires moving the signer into Lean (or into an audited side-car)
and is an explicit future direction, not this slice's scope.

The attestation schema is versioned (`schema_version`); each version
fixes a canonical signed-payload shape forever. Future additions (e.g.
request-digest binding in slice 4) must bump the version, not modify
v1. See `python/attestation.py`'s module docstring for the full
forward-compatibility contract.

## Invariants enforced by CI

`tests/test_bypass_invariant.py` fails the build if:

- Python reintroduces decision branching on `Signal`, `ExitDecision`,
  or `PositionSize`. The check uses Python's `re` with word-boundaries
  (`\bif\b.*\b(Signal|ExitDecision|PositionSize)\b`) so theorem and
  function names that merely *contain* a type keyword as a substring
  (e.g. `verifySignal_approve_implies_consistent`) are not flagged —
  only real conditional statements branching on these types are.
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
- A new **caller integration** → a subdirectory under
  `examples/external_integration/`, next to the Anthropic SDK and
  LangGraph demos. Shows how one specific kind of caller wires itself
  to the verifier. Never branches on Veritas types.
- A new **venue adapter** (Hyperliquid-style observer/executor) →
  **not on the roadmap.** The caller is responsible for venue
  connectivity. Only add one if you're extending the bundled example
  runner for demo purposes, and be aware that investing time in it
  will not advance any release milestone.

Exchange integrations, runners, dashboards, and journals are
**secondary adapters**, not the product core. Keep them demotable.

## Source tagging

The bundled example runner tags its trades `mock`, `testnet`, or
`mainnet`. Never mix sources in reliability calculations without
explicit filtering.

## Gate files carry first-class theorems

Every file under `Veritas/Gates/` exports a soundness theorem that
states what an Approve (or Resize) verdict from that gate *means*,
not just what it computes. These theorems are the gate layer's
public contract:

- `Gates/SignalGate.lean` — `verifySignal_approve_implies_consistent`
- `Gates/ConstraintGate.lean` — `checkConstraints_approve_within_ceiling`,
  `checkConstraints_resize_respects_ceiling`
- `Gates/PortfolioGate.lean` — `checkPortfolio_approve_respects_cap`
- `Gates/Certificate.lean` — `certificate_soundness` (combined)

When adding a new gate or extending an existing one, ship the
soundness theorem alongside the dispatch function. A gate without
its own soundness theorem is a dispatcher, not a verifier.

## Roadmap scope

Veritas ships in slices; each slice must leave `lake build`
sorry-free and `pytest` green. What counts as a slice:

- A new gate, or a deeper soundness theorem on an existing gate
- A new strategy that makes Gate 1's multi-policy arbitration
  non-trivial at a new N
- Trust-infrastructure work: signed certificates, public theorem
  registry, reproducible builds, freshness/revocation
- Caller-facing API / SDK polish on the HTTP, MCP, and Python surfaces

What is **not** a slice and does not gate any release (v0.1 or later):

- Exercising `HyperliquidObserver` / `HyperliquidExecutor` against
  real testnet or mainnet traffic
- Adding a second or third venue adapter
- Running the bundled example runner as a real trading loop
- Dashboard / playground visual polish beyond what the verifier
  surface needs to demo

The shipping test for any release is verifier correctness, not
integrator behavior: `tests/test_gates.py`, `tests/test_api_endpoints.py`,
`tests/test_mcp_server.py`, and `tests/test_bypass_invariant.py` pass
and `lake build` produces a sorry-free binary.
