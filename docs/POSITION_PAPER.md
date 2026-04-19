# A trust boundary for agent-native finance

*Veritas project — April 2026*

## Abstract

Agent-native trading is arriving faster than the tooling to make it
safe. Most of the public discussion frames the problem as prediction
quality — can this agent beat the market? — and invests accordingly
in larger models, richer feature sets, and denser backtests. We argue
that the more load-bearing failure of current agent stacks is
different: they cannot give a caller a legible account of what they
are about to do, under what assumption, inside what envelope, and
against what existing portfolio. They do not have a trust boundary.

Veritas is a narrow response to this. It is a Lean-backed pre-trade
verifier: a fixed function from (proposal, constraints, portfolio) to
(verdict, reason codes, attached assumptions, final approved
notional). It is not a trading agent, a strategy engine, or an
exchange integration. It is the gate a trading agent calls before
capital moves.

This paper states the problem, the design choices Veritas makes, and
the limits of the v0.1 system. It claims less than most formal-methods
finance writing; the claims it does make are scoped to the Lean
kernel.

## 1. The problem is not prediction quality

The most visible failure of automated trading agents is that they
lose money. The most visible fix, therefore, is that they should
predict better. Every LLM-trading-agent release ships a benchmark
bar chart.

Empirically, though, the first several generations of agent stacks
fail in a recognizable second way: they take trades their human
operators would have blocked if they had been given the chance. An
agent decides to lever up a correlated basket one minute before a
scheduled Fed release. An agent opens a ten-percent notional position
on a pair whose liquidity it has not traded before. An agent doubles
down on a rejected thesis because the reviewer prompt does not
surface the reject.

These failures are not prediction failures. They are *approval*
failures. The agent knew what it wanted to do; nothing in the system
forced it to articulate the claim, check the claim against an
envelope, and account for existing exposure before committing.

The industry response so far has been either (a) add another LLM to
critique the first one, or (b) bolt post-trade risk controls on top
of an opaque decision loop. The first restates the problem in a
larger system. The second is reactive by construction — it learns
about a breach after the money has moved.

Between intent and execution, there should be a *pre-trade* gate
that is (i) narrower than the agent, (ii) legibly auditable, and
(iii) not produced by the same process that produced the trade. This
is the space Veritas occupies.

## 2. What a verifier should be

The formal-methods community has decades of experience with tools
that sit between a producer and a consumer and discharge obligations
on the producer's behalf. Model checkers, static analyzers, type
systems, SMT solvers. The design pattern is consistent: small,
fixed input contract; small, structured output; no shared state with
the caller; decision kernel isolated from I/O.

A trading-agent verifier deserves the same shape. We adopted it
directly:

- **Small fixed contract.** A `TradeProposal`, an `AccountConstraints`,
  a `Portfolio`. Every field is a simple value. No callbacks, no
  futures, no handles.
- **Small structured output.** A `Certificate` consisting of three
  per-gate verdicts (approve / resize / reject) plus reason codes and
  attached assumptions. No exceptions.
- **No shared state.** Veritas is a pure function. There is no
  session, no token, no subscription. A run is a run.
- **Isolated kernel.** The gate logic lives in a Lean 4 kernel
  compiled to a native binary. The Python adapters that speak HTTP,
  MCP, and SQLite do not contain gate decisions and are CI-prevented
  from re-introducing them.

A verifier with this shape composes well with existing agents. A
caller can migrate by adding one call per proposal, with no
architectural change to its policy engine. The verifier does not
require access to the caller's alpha, model weights, or prompts — it
only needs the output of the decision the caller is about to make.

## 3. The three gates

We decompose the approval obligation into three orthogonal
questions. Each is a gate; each returns one of *approve*, *resize*,
or *reject*.

**Gate 1 — signal consistency.** Given the proposed trade and the
market context the caller claims to be acting under, does the
proposal cohere? In particular: does the direction match what a
declared policy would emit here, and does the proposal carry
well-formed, non-empty assumptions? Gate 1 forces the caller to be
explicit about what it is betting on.

**Gate 2 — strategy-constraint compatibility.** Given the caller's
account envelope (equity, reliability of the attached assumption,
sample size, leverage cap, stop-loss), is the requested notional
inside the ceiling? Gate 2 returns the ceiling when the caller is
over it (*resize*), rather than silently approving at the larger
number. Gate 2 rejects when no non-zero size is admissible — below
the reliability threshold, or with non-positive leverage.

**Gate 3 — portfolio interference.** Given the caller's existing
positions and the (possibly resized) proposal, does the combined
exposure violate portfolio-wide constraints? v0.1 catches
opposite-direction conflicts and enforces a gross-notional cap;
v0.2 will handle multi-asset correlation once a second policy is
active.

The gates execute in order. Gate 2 sees the original proposal; Gate
3 sees the Gate 2 output. If any gate rejects, downstream gates
receive `upstream_gate_rejected` and the final notional is zero.

## 4. Why Lean

The design of Veritas leans on Lean 4 for the kernel. Two properties
matter:

**The kernel's API surface is compile-checked.** Veritas uses Lean's
type system to encode properties that would otherwise be invariants
maintained by convention: exit reasons are a sum type with three
constructors; `ReliabilityStats` carries `wins ≤ total` at the type
level, so the constructor cannot be called with inconsistent counts;
the `Verdict` type has three tags, each with the data needed for
that tag and nothing more. The caller gets a structured value it can
pattern-match on, not a schemaless JSON blob.

**Numeric behavior is backed by theorems.** `Finance.PositionSizing`
ships five theorems — non-negativity, 25 % cap, zero at no edge,
monotonicity in reliability, exploration cap at 1 %. `Strategy.ExitLogic`
ships `exitReason_exhaustive`. `Learning.Reliability` ships
`reliabilityUpdate_bounded` (reliability ∈ [0, 1]) and
`reliabilityUpdate_monotone_on_wins`.

These are not the only things that could be proved. They are the
things that matter for Gate 2 and for the learning substrate. Each
theorem eliminates a category of silent miscount; collectively they
give a reviewer a small set of facts about which to argue.

The cost is that Lean's `Float` is an opaque FFI type with no
algebraic library, so the theorems depend on 20 axioms capturing
IEEE 754 ordering and arithmetic. 13 are exact; 7 are
rounding-dependent within the numeric ranges Veritas uses. Reducing
the rounding-dependent axioms — ideally to zero by migrating to
exact arithmetic for policy decisions — is the chief v0.2 technical
goal. The axiom set is disclosed up front; hiding it would be a
trust regression.

## 5. Claim discipline

We want to be clear about the scope of the properties Veritas
publishes.

**What Veritas verifies.** That the approved notional returned by
the Lean kernel satisfies the theorems stated in
`Finance.PositionSizing`. That every exit classified by
`Strategy.ExitLogic` is one of three exhaustive reasons. That
reliability updates stay in [0, 1] and are monotone on wins. That
each gate in `Veritas/Gates/` executes the pure function its
specification describes.

**What Veritas does not verify.**

- The correctness of the caller's alpha. If the caller submits an
  adversarial proposal with a fabricated funding rate, Gate 1 will
  check that funding rate against policy but will not know that it
  is fabricated.
- The correctness of the bundled funding-reversion policy. Veritas
  verifies that the policy is applied consistently; it does not claim
  the policy is profitable.
- Anything about a specific execution venue. After the certificate is
  issued, what the caller does is the caller's problem.
- Float-level numerical edge cases outside the ranges Veritas uses
  (probabilities in [0, 1], Kelly fractions, small Nat counts). Our
  rounding-dependent axioms are scoped to these ranges.
- Correctness of the Python transport. An adapter bug could fail to
  deliver a certificate to a caller; no theorem prevents that. The
  caller is expected to treat missing certificates as rejections.

This list will grow. Treat it as a guardrail against overclaiming,
not as a disclaimer.

## 6. Related work

Automated risk checks are standard infrastructure at institutional
trading desks; the novelty is not the category, it is the
combination of (i) agent-native contract, (ii) Lean-backed kernel,
and (iii) public, legible certificates.

Formal-methods work in finance has historically concentrated on
smart-contract verification. Tools like Certora and the Move prover
formalize on-chain logic. Veritas formalizes *off-chain policy* —
the step that decides whether an order should be sent at all — and
leaves the on-chain side to existing tools.

Agent-evaluation work (Inspect, Agentbench, OpenAI/GDPval) focuses
on benchmarking and pre-deployment testing. Veritas is orthogonal:
it is a run-time gate, not a pre-deployment screen.

## 7. Roadmap

The v0.1 product has one bundled policy and a single-asset Gate 3.
The sequence of activations beyond v0.1 is:

- **v0.2.** A second policy (basis, liquidation-cascade reversal, or
  cross-exchange perp-perp basis, candidates under evaluation). Gate
  1 dispatches over a policy registry; Gate 3 gains multi-asset
  correlation. Concurrently: migrate numeric decision paths off
  `Float` where practical to eliminate rounding-dependent axioms.
- **v0.3.** Assumption library exposed as a read-only oracle.
  Certificates carry a hash of the Lean theorem they ultimately rest
  on, so callers can verify the trust claim without running the
  kernel themselves.
- **v0.4+.** Public registry of policies and theorems, cross-asset
  policies, first cross-agent integrations.

Each step adds surface, and each step therefore costs trust. The
default is not to take the step until the previous step's trust is
deployed.

## 8. Closing

The question a trading agent should answer before touching capital
is not "what do you want to do?" but "what do you want to do, under
what assumption, inside what envelope, against what you already
hold, and why?". Veritas exists because nothing else in the
agent-native stack asks that question in a way the caller can be
forced through and the reviewer can audit. We would rather have a
small, legible gate than a large, opaque trader. The v0.1 product
is the smallest such gate we could ship while keeping all three
questions on the critical path.
