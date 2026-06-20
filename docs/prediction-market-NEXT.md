# Resume note — Prediction-Market direction

> Personal handoff doc. Read this first when you come back; it points to
> everything else. Last working session: 2026-06-14.

## TL;DR — where we are

1. **Shipped this session** (demo/Pages polish on Veritas v0.4) — all done & pushed.
2. **Decided a new strategic direction**: re-point Veritas at **prediction
   markets** (Polymarket / Kalshi / Manifold). The full design is in
   **[`docs/prediction-market-slice.md`](prediction-market-slice.md)**.
3. **Not started yet**: building the slice. Resume at §"Next actions".

---

## Part A — what got shipped this session (Veritas v0.4)

Four tasks + one follow-up, all committed to `main` and live:

| Item | Result |
|---|---|
| Fix `demo.sh` | Rewired to v0.4 CLI (`emit-certificate`→`emit-certificate-ex`, Bayesian args, updated theorem inventory). Runs clean. |
| Clean `journal.db` | Untracked + gitignored (rows carry per-run timestamps → always dirty). `events.jsonl`/`summary.md` remain the committed text artifacts. |
| README Demo section | Added with approve/resize/reject + dashboard screenshots (`docs/assets/`). |
| GitHub Pages | **Live: https://lizjq66.github.io/Veritas/** (gh-pages branch root, built by `web/build_static_demo.py`). |
| Commit/push + archive | `main` pushed; **Lean-Veritas repo archived** on GitHub. |
| Follow-up | Stripped dead `/runner` links from the hosted static demo (404'd on Pages). |

Relevant commits on `main`: `2105872`, `32789d9`, `d094a6d`.

---

## Part B — the strategic discussion (prediction markets)

### Why prediction markets fit Veritas

Veritas is a Lean-backed pre-trade verifier: `(proposal, constraints,
portfolio) → signed certificate`, through three gates. Prediction
markets are a *cleaner* fit than perps because they make explicit the
two things the verifier reasons about:

- **Probability** — a PM price *is* an implied probability; the agent
  produces a competing estimate; edge = `estimatedProb − marketPrice`.
- **Ground truth** — every market resolves YES/NO at a known time, so
  the Bayesian `(successes, failures)` calibration input gets *clean,
  timestamped* labels instead of the fuzzy "was the signal right?" of
  perps.

### Why almost no new code is needed (the key insight)

Veritas separates two layers, and **only the domain-specific one is
pluggable — and that's the only one prediction markets change**:

| | What | Who owns it | Change for PM? |
|---|---|---|---|
| "What direction to believe" | signal / strategy / assumptions | **strategy registry** (pluggable since v0.2) | ✅ add a PM strategy |
| "Given a belief, how much to risk / will it blow up" | Kelly + Bayesian + portfolio | Gate 2/3 universal, **already proved & generalized** | ❌ no change |

Per gate:

- **Gate 1** (`SignalGate.verifySignal`): its soundness theorem
  `verifySignal_approve_implies_consistent` is **generic over the
  registry** — never mentions funding/BTC. Adding a PM strategy = adding
  a list element to `allStrategies`; the theorem covers it for free.
- **Gate 2** (`ConstraintGate` / `PositionSizing`): `kellyFraction
  (winProb, winLossRatio)` already takes **arbitrary odds** and is
  proved for them. The perp sizer just hardcodes `winLossRatio = 1`
  (even money — a *special case*). A YES bet at price `p` has odds
  `b = (1−p)/p`. Swap the one argument → exact binary Kelly. The
  no-edge cutoff generalizes from `1/2` to `marketPrice` (since `1/2`
  is the `p=1/2` case). The Bayesian layer (`BetaPosterior`,
  `posteriorMean`, 11 theorems) is market-agnostic → reused verbatim.
- **Gate 3** (`PortfolioGate`): correlation-weighted exposure is pure
  portfolio math, no market-type assumption → reused as-is (one caveat:
  PM volatility semantics for the VaR leg need an audit).

**Net new work:** ~1 strategy file + ~1 sizer file + ~6 theorems (5
mechanical mirrors of existing perp theorems + 1 trivial), plus
defaulted fields and additive wiring. Everything else is reuse.

---

## Part C — the three gates (quick reference)

- **Gate 1 — signal consistency** (`Veritas/Gates/SignalGate.lean`):
  ≥1 strategy fires, all agree on direction, proposal matches, ≥1
  assumption attached. Doesn't touch capital.
- **Gate 2 — constraint compatibility** (`Veritas/Gates/ConstraintGate.lean`,
  sizer in `Veritas/Finance/PositionSizing.lean`): Bayesian posterior
  over wins/losses → exploration (<10 obs: 1% flat) / exploitation
  (half-Kelly, 0 if no edge, hard cap 25% equity). Returns
  Approve/Resize/Reject.
- **Gate 3 — portfolio interference** (`Veritas/Gates/PortfolioGate.lean`):
  same-asset direction conflict, correlation-weighted gross-exposure
  cap, projected-VaR bound.
- Combined by `Veritas/Gates/Certificate.lean` (`certificate_soundness`).

---

## Part D — open decision (decide before/while building)

**How does the new resolution-risk gate (Gate R) enter the certificate?**

- **Option A** — add a 4th gate field to `Certificate`. Cleanest as a
  product story ("four gates"), but touches `Certificate`,
  `certificate_soundness`, CLI emitter, `bridge.py`, `schemas.py`, and
  the **versioned attestation payload** (bumps `schema_version`).
- **Option B (recommended for MVP)** — fold resolution checks into the
  PM Gate-1 path as reject codes; ship the standalone gate later. Zero
  schema churn.

Currently the design doc defaults to **B**. Change it if you want A as a
selling point.

---

## Part E — next actions (resume here)

The slice plan (each step leaves `lake build` sorry-free + `pytest`
green — the repo's release rule):

1. **Slice 1 — Types + PM Kelly (isolated, no wiring).** Add
   `MarketType` + PM fields (defaulted) to the types; write
   `calculatePositionSizeFromPosteriorPM` (in a new
   `Veritas/Finance/PositionSizingPM.lean`) + its 4 theorems (mirror
   the `positionSize_fromPosterior_*` proofs). **This alone proves the
   core thesis.** ← _good first pickup point_
2. Slice 2 — Gate 1 PM strategy: `Veritas/Strategy/ProbEdge.lean` +
   registry entry + `marketType` filter.
3. Slice 3 — Gate 2 PM dispatch: `checkConstraintsPM` + CLI + `bridge.py`
   + `verifier.py` routing + `test_gates.py` PM cases.
4. Slice 4 — resolution checks (option B): reject codes on the PM
   Gate-1 path.
5. Slice 5 — certificate enrichment (`attested_probability`,
   `methodology_hash`; schema bump) + a PM demo preset reusing the
   `web/build_static_demo.py` gallery + short paper.

**Two things I offered to do next that you haven't picked yet:**
- Walk a concrete numeric example (buy YES @ 0.40, you estimate 0.55)
  through all three gates, vs the same on perps.
- Start writing Slice 1.

---

## Pointers

- Design doc: [`docs/prediction-market-slice.md`](prediction-market-slice.md) — gate specs (with Lean skeletons), theorem list (R/R\*/N), full reuse map, wire changes, slice plan, honest gaps.
- Repo: `/Users/cybernvwa/Desktop/Veritas` · `github.com/lizjq66/Veritas` (you have ADMIN).
- Contributor contract / trust boundary: `CLAUDE.md`.
- Key files to reread when resuming: `Veritas/Finance/Kelly.lean`,
  `Veritas/Finance/PositionSizing.lean`, `Veritas/Gates/SignalGate.lean`,
  `Veritas/Strategy/Registry.lean`.
