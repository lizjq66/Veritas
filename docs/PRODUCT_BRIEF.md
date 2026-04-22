# Veritas v0.1 — Product Brief

> Veritas is a Lean-backed pre-trade verifier. A calling trading agent
> submits a proposed trade; Veritas runs it through three gates and
> returns a structured approve / resize / reject certificate with
> machine-readable reason codes. Trust infrastructure for agent-native
> finance, narrowly scoped.

---

## 1. Thesis

The next wave of automated trading will be dominated by agent-native
systems: LLMs and custom policies acting on capital through exchange
APIs. These systems produce novel alpha ideas at high rates. Almost
none of them are trustworthy under adversarial market or model
conditions, and almost none of them can give a caller a legible
account of *what they are about to do and why*.

Building a better autonomous trader is one response. Building a
**trust boundary** between whatever the caller is and the capital it
controls is a different — and, we think, more strategically durable —
response.

Veritas takes the second path. It is a small, fixed surface:

    (proposal, constraints, portfolio)  →  certificate

A trading agent calls it; Veritas does not call anything. The kernel
is Lean 4, pure, type-checked, with theorems governing its core
numeric behavior. The adapters (HTTP, MCP, subprocess bridge,
exchange connectors) live in Python and are explicitly untrusted.

### What this product is not

- Not an autonomous trader. It holds no view, runs no loop, owns no capital.
- Not a strategy factory. It verifies proposals; it does not produce them.
- Not a Hyperliquid product. The bundled example runner targets
  Hyperliquid because the demo has to target something, but the
  verifier itself has no venue coupling.
- Not a framework. There is a small, opinionated set of three gates
  and a single Certificate type. Callers do not extend Veritas; they
  call it.

### Why a verifier is the right v0.1

A verifier is strictly smaller than a full trading agent, so it can
be held to a stricter formal standard. All gate logic lives in Lean,
with proofs backing the numeric core. A trader that owned its own
strategy engine would blur this boundary the moment the strategy
engine took a decision the type system could not see.

A verifier is also the easier product to integrate. Any existing
trading agent, LLM, or rules engine can adopt Veritas without
surrendering its own alpha — it keeps its ideas, Veritas supplies the
policy envelope and the approval trace. Adoption does not require
migration.

---

## 2. The three gates

### Gate 1 — signal consistency

**Question.** Is the proposed trade internally coherent?

**Input.** `TradeProposal` (direction, notional, price, funding rate,
timestamp, open interest).

**Output.** `approve + assumptions` / `reject + reason codes`.

**v0.1 implementation.** `Veritas/Gates/SignalGate.lean` checks the
proposal against Veritas's built-in funding-reversion policy. If the
policy would emit a signal in this context, and the proposal's
direction agrees with it, Gate 1 approves and attaches the assumption
`funding_rate_reverts_within_8h`. Otherwise Gate 1 rejects with one of:

- `no_signal_under_policy` — context is below the funding threshold
- `direction_conflicts_with_signal` — caller proposed LONG where the
  policy would signal SHORT, or vice versa
- `malformed_proposal_no_assumptions` — no assumption could be attached

Extending Gate 1 is how multi-policy, multi-strategy support will
arrive. v0.2 will accept a registry of policies and will check
mutual consistency when multiple fire at once.

### Gate 2 — strategy-constraint compatibility

**Question.** Does the proposal fit the account's policy envelope?

**Input.** `TradeProposal` + `AccountConstraints` (equity, reliability,
sample size, max leverage, max position fraction, stop-loss %).

**Output.** `approve` / `resize(new_notional)` / `reject + reason codes`.

**v0.1 implementation.** `Veritas/Gates/ConstraintGate.lean` delegates
the ceiling to `Finance.PositionSizing.calculatePositionSize`, which
carries five theorems:

| Theorem | Guarantee |
|---|---|
| `positionSize_nonneg` | ceiling ≥ 0 |
| `positionSize_capped` | ceiling ≤ 25 % of equity |
| `positionSize_zero_at_no_edge` | reliability ≤ 0.5 → ceiling 0 |
| `positionSize_monotone_in_reliability` | ceiling monotone in reliability |
| `positionSize_explorationCapped` | first 10 samples → 1 % of equity |

Any value Gate 2 approves or resizes to is bounded by this ceiling.
Rejection paths: non-positive leverage, non-positive notional, zero
edge. This is the gate whose formal content is strongest in v0.1.

### Gate 3 — portfolio interference

**Question.** Does the proposal clash with existing positions?

**Input.** `TradeProposal` + `Portfolio` (existing positions + max
gross exposure fraction).

**Output.** `approve` / `resize(headroom)` / `reject + reason codes`.

**v0.1 implementation.** `Veritas/Gates/PortfolioGate.lean` rejects
when the new proposal conflicts in direction with any existing
position (`direction_conflicts_existing_position`) and resizes down
when total gross notional would exceed the configured cap. If the
portfolio is already at the cap, Gate 3 rejects
(`portfolio_already_at_correlation_weighted_cap`).

v0.1 treats all positions as fully correlated. True multi-asset
correlation is a v0.2 concern and will arrive alongside multi-policy
Gate 1.

---

## 3. Architecture

```
                 calling agent (not Veritas)
                           │
                  TradeProposal + constraints + portfolio
                           │
                           ▼
    ┌────────────────────────────────────────────────────┐
    │   Python transport / adapters (untrusted)          │
    │     verifier.py   — canonical entry point          │
    │     bridge.py     — JSON bridge to Lean kernel     │
    │     api/routes/verify.py  — POST /verify/*         │
    │     mcp/server.py — MCP tool `verify_proposal`     │
    └────────────────────────────────────────────────────┘
                           │
                   subprocess + JSON
                           │
                           ▼
    ┌────────────────────────────────────────────────────┐
    │   Lean 4 verification kernel (trusted)             │
    │     Gates/Types.lean                               │
    │     Gates/SignalGate.lean      — Gate 1            │
    │     Gates/ConstraintGate.lean  — Gate 2            │
    │     Gates/PortfolioGate.lean   — Gate 3            │
    │     Gates/Certificate.lean     — combined trace    │
    │     Finance/PositionSizing.lean (+ 5 theorems)     │
    │     Strategy/ExitLogic.lean (+ exhaustiveness)     │
    │     Learning/Reliability.lean (+ bounded, monotone)│
    └────────────────────────────────────────────────────┘
                           │
                           ▼
                     Certificate
          (verdict × 3, assumptions, final notional)
```

### Who is who

| Component | Responsibility | Trust |
|---|---|---|
| Calling trading agent | Produces proposals, decides when to trade, executes after approval. Owns its own alpha. | Caller's problem. |
| Veritas Python surface | Transport. Marshals proposals to the kernel, returns certificates to callers. | Untrusted. |
| Veritas Lean kernel | Runs the three gates. Pure functions, type-level invariants, theorems. | Trusted. |
| Venue adapter (e.g. Hyperliquid) | Observes markets, sends approved orders. | Caller's problem. |

The caller is in charge of market data, alpha, and execution. Veritas
is in charge of approval. This separation is the point.

### What Veritas does not do

- It does not place orders. Approved notionals are handed back to the
  caller.
- It does not observe markets. The caller supplies the context.
- It does not persist state. Veritas is a pure function; any journal
  lives outside the kernel (the bundled runner uses SQLite, but the
  verifier does not read from it).
- It does not have a trading loop. The caller calls Veritas per
  proposal; there is no heartbeat.

---

## 4. Where the funding-reversion policy fits

The bundled policy (funding-rate mean reversion on perps) is an
**example policy family**, not the product identity. It exists to:

1. Give Gate 1 a concrete rule to check against out of the box.
2. Give the bundled example runner a real decision-producing caller,
   so readers can see both sides of the boundary.
3. Keep the v0.1 assumption library non-empty
   (`funding_rate_reverts_within_8h`), so reliability-based Gate 2
   behavior can be exercised.

If the funding policy were removed, Veritas would still be useful
(callers could bring their own policies), but Gate 1 would need a
different backing check. v0.2 reframes this: the policy becomes a
plugin registry and Gate 1 dispatches to the matching entry.

Hyperliquid is the same story. The observer and executor adapters
target Hyperliquid because the demo has to target something, but the
verifier itself never speaks to Hyperliquid.

---

## 5. Implementation status

### What is shipping in v0.1

- **Verifier surface**: Python `Verifier`, HTTP `POST /verify/*`, MCP
  `verify_proposal`.
- **Three gate CLIs**: `verify-signal`, `check-constraints`,
  `check-portfolio`, `classify-exit`, `emit-certificate` on the Lean
  binary.
- **Theorems**: all proved, 0 sorries, 0 Veritas-specific axioms
  (decision-path arithmetic runs on exact `Rat` via Mathlib as of v0.2
  Slice 5; proofs depend only on Lean's foundational `propext`,
  `Classical.choice`, `Quot.sound`).
- **Invariant tests**: CI-enforced grep against Python decision logic,
  gate bypass, and direct kernel invocation outside the bridge.
- **Example runner**: `python/main.py` demonstrates a caller that
  invokes the verifier on every tick.
- **Observation layer**: read-only `GET /state`, `/assumptions`,
  `/trades`, `/verify/theorem/{name}`; dashboard; MCP inspection tools.
- **SQLite journal + events.jsonl + summary.md**: deterministic demo
  artifacts committed under `tests/demo_output/`.

### What is explicitly out of scope for v0.1

- Multi-policy Gate 1 (Gate 1 dispatches to a single policy in v0.1;
  v0.2 activates it against a policy registry).
- True multi-asset Gate 3 correlation (v0.1 treats all positions as
  fully correlated).
- ~~Removing rounding-dependent Float axioms~~ (v0.2 Slice 5 — done; see below).
- ZK certificate issuance (v0.3+).
- Public registry of assumptions / theorems (v0.3–v0.4).
- **Live exchange execution as a v0.1 ship requirement.** Veritas
  v0.1 is a verifier, not a trader. Whether the bundled example
  adapters (`HyperliquidObserver`, `HyperliquidExecutor`) have been
  exercised against Hyperliquid testnet is a v0.2+ concern. Their
  correctness does not gate v0.1 completion; the verifier API
  contract does.
- Mainnet capital.

### v0.1 completion criteria

Veritas v0.1 ships when — and only when — the following are true:

1. **Verifier API contract holds against fixture proposals.** The
   `Verifier` Python surface, the `POST /verify/*` HTTP surface, the
   MCP `verify_proposal` tool, and the `veritas-core` CLI all
   produce the same certificate for the same input. Enforced by
   `tests/test_gates.py`, `tests/test_api_endpoints.py`, and
   `tests/test_mcp_server.py`.
2. **All three gates cover their approve / resize / reject paths.**
   Gate 1 must accept coherent proposals, reject wrong-direction and
   silent-policy proposals; Gate 2 must approve within the ceiling,
   resize above it, reject at no edge; Gate 3 must approve empty
   portfolios, reject direction conflicts, resize on cap breach.
   Enforced by `tests/test_gates.py`.
3. **Python cannot bypass the Lean kernel.** No Python file branches
   on Veritas decision types, mints `Verdict` values outside the
   schema layer, or invokes `veritas-core` outside the bridge.
   Enforced by `tests/test_bypass_invariant.py`.
4. **Lean kernel is sorry-free, with disclosed axioms.** `lake build`
   produces the binary with zero `sorry` and zero Veritas-specific
   axioms. `Finance/FloatAxioms.lean` was deleted in Slice 5 — all
   decision-path arithmetic runs on exact `Rat` backed by Mathlib.
5. **Full test suite is green.** `python -m pytest tests/` passes in
   full. Runner-level tests (`test_loop.py`, `test_live_runner.py`)
   exercise the bundled example adapters only against the in-process
   fakes.

Criteria Veritas v0.1 **does not include**:

- Any number of real trades placed on Hyperliquid testnet or any
  other venue.
- Any SLA on the example adapters under real network conditions.
- Any consecutive-days uptime requirement.

Callers who care about live execution against a specific venue
should treat adapter correctness as their own responsibility. The
verifier's job is to return the same certificate for the same input,
and to keep that contract stable across kernel versions.

---

## 6. Decision principle

Any design question resolves against this spine:

> **Does this change tighten the verifier, or does it bloat it?**

Tightening = smaller surface, more legible approval traces, sharper
theorems, fewer axioms, clearer separation between caller and
verifier.

Bloating = a new subsystem Veritas owns end-to-end, a new venue
integration at the core, a new abstraction layer without a concrete
v0.1 use.

The second path is where trust infrastructure projects usually fail.
Veritas keeps itself to the first.
