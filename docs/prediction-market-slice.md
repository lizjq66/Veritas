# Prediction-Market Slice — Design Doc

> Status: proposal. A vertical slice that re-points the Veritas verifier
> at prediction markets (Polymarket / Kalshi / Manifold style) with
> maximum reuse of the existing three-gate kernel. Nothing here is built
> yet; this is the spec + theorem list + reuse map to build against.

## 0. Thesis

Prediction markets are a *cleaner* fit for Veritas than perpetual
futures, because they make explicit the two things the verifier is built
to reason about:

- **Probability.** A PM price *is* an implied probability. The agent's
  job is to produce a competing probability estimate. The "edge" is
  `estimatedProb − marketPrice`, exactly the input a Kelly sizer wants.
- **Ground truth.** Every market resolves to YES/NO at a known time.
  "Was the assumption correct?" stops being fuzzy (as on perps) and
  becomes a clean, timestamped binary label — exactly the `(successes,
  failures)` the Bayesian reliability layer already consumes.

The headline reuse fact: **Kelly is already exact and already proved.**
`Veritas/Finance/Kelly.lean` defines `kellyFraction (winProb
winLossRatio)` with `kellyFraction_nonneg` and `kellyFraction_mono`.
The current sizer calls it with `winLossRatio = 1` (even money). A
prediction-market bet of *buy YES at price `p`* has net odds `b =
(1 − p) / p`. Passing the real odds turns the existing, already-proved
Kelly into an exact binary-market sizer — a one-argument change at the
call site, not a new theory.

## 1. Scope of the MVP slice

**In:**
- A new market type discriminator so PM proposals and perp proposals
  never cross-fire.
- One PM Gate-1 strategy (`prob_edge`) in the registry.
- A PM Gate-2 sizer: exact binary Kelly off the market price, with the
  same four soundness theorems as the perp sizer.
- A new Gate (`resolution_gate`) for PM-specific risk (resolution
  source trust + time-to-resolution).
- Certificate/wire/CLI plumbing for the new inputs.

**Out (explicitly deferred):**
- Scalar / categorical (non-binary) markets — binary YES/NO only.
- Live venue adapters (Polymarket/Kalshi clients) — caller's job, per
  `CLAUDE.md`'s "caller brings venue connectivity" boundary.
- A full Beta-quantile lower bound (needs inverse-Beta-CDF, breaks
  `Rat` purity); reuse the existing `pessimisticMean` failure-shift
  instead.
- Cross-market correlation *table* auto-population — caller supplies
  correlations, same as today.

## 2. Domain model — PM concepts mapped onto existing types

| PM concept | Veritas type | Mapping |
|---|---|---|
| Buy YES / Buy NO | `Direction` (`Veritas/Types.lean`) | `YES ↦ Long`, `NO ↦ Short`. No new type. |
| Market implied prob | new `TradeProposal.marketPrice : Rat` | the YES price ∈ (0,1). |
| Agent's estimate | new `TradeProposal.estimatedProb : Rat` | what the strategy compares against `marketPrice`. |
| Edge | derived | `estimatedProb − marketPrice`. |
| Calibration history | `AccountConstraints.{successes,failures,priorAlpha,priorBeta}` | **unchanged** — already a Beta posterior. |
| Resolution source | new `TradeProposal.resolutionTrust : Nat` (tier 0–3) | consumed by the new resolution gate. |
| Time to resolution | new `TradeProposal.secondsToResolution : Nat` | consumed by the new resolution gate. |
| Market type | new `TradeProposal.marketType : MarketType` | `Perp \| BinaryPM`; filters the registry. |

Notional, equity, position-fraction cap, gross-exposure cap, correlation
table, `Verdict`, `Certificate`, `Assumption` — all reused verbatim.

## 3. Gate-by-gate specification

### Gate 1 — signal consistency (REUSE, add strategy)

`verifySignal` and its soundness theorem
`verifySignal_approve_implies_consistent` are **generic over the
registry** (`Veritas/Gates/SignalGate.lean`). They do not change.

Add a strategy to `allStrategies` (`Veritas/Strategy/Registry.lean`),
following the `FundingReversion` pattern:

```lean
-- Veritas/Strategy/ProbEdge.lean  (NEW)
def probEdgeMargin : Rat := 1 / 50   -- 2% edge required to fire

def decideProbEdge (snap : MarketSnapshot) : Option Signal :=
  if snap.marketType ≠ MarketType.BinaryPM then none
  else if snap.estimatedProb > snap.marketPrice + probEdgeMargin then
    some { direction := Direction.Long,  .. }   -- buy YES
  else if snap.estimatedProb < snap.marketPrice - probEdgeMargin then
    some { direction := Direction.Short, .. }   -- buy NO
  else none
```

`extractAssumptions` returns the methodology claim ("estimate produced
by method M over evidence E"). Perp strategies already self-gate on
missing inputs (basis needs `spotPrice`, cascade needs
`liquidations24h`); the `marketType` guard makes the separation total
in both directions.

**No new Gate-1 theorem** — the existing soundness theorem now covers
the PM strategy for free, because it quantifies over whatever the
registry fires.

### Gate 2 — constraint compatibility (REUSE Kelly, new sizer + 4 theorems)

The perp sizer (`Veritas/Finance/PositionSizing.lean`) hardcodes even
money:

```lean
let kellyFrac := kellyFraction b.posteriorMean 1   -- b = 1 (even money)
... zero if posteriorMean ≤ 1/2 ...
```

The PM sizer passes the *real* market odds and shifts the no-edge cutoff
from `1/2` to the market price:

```lean
-- Veritas/Finance/PositionSizingPM.lean  (NEW)
def calculatePositionSizeFromPosteriorPM
    (equity marketPrice : Rat) (b : BetaPosterior) : Rat :=
  if b.successes + b.failures < explorationThreshold then
    equity * explorationFraction
  else if b.posteriorMean ≤ marketPrice then 0           -- no edge vs price
  else
    let odds      := (1 - marketPrice) / marketPrice      -- net odds b
    let kellyFrac := kellyFraction b.posteriorMean odds
    let halfKelly := kellyFrac * (1 / 2)
    let rawSize   := equity * halfKelly
    let cap       := equity * exploitationCap
    if rawSize > cap then cap else rawSize
```

`explorationThreshold`, `explorationFraction`, `exploitationCap` are
reused unchanged. The four theorems mirror the perp sizer's and reuse
its proof structure almost verbatim (see §4).

`checkConstraintsPM` in `ConstraintGate.lean` calls the PM sizer and
returns the same `Verdict` shape (Approve / Resize / Reject), so the
gate's resize/ceiling theorems carry over with the sizer swapped.

### Gate 3 — portfolio interference (REUSE as-is)

`checkPortfolio` (`Veritas/Gates/PortfolioGate.lean`) already does
correlation-weighted gross-exposure and a linear-VaR bound over
`(asset, volatility, correlations)`. Prediction-market positions are
*more* correlated than perps ("Trump wins" vs "GOP Senate"), so this
gate matters more, but needs **no structural change**: the caller
supplies the correlation table exactly as today.

Caveat to validate during build: PM payoffs are bounded in `[0,1]`, so
`volatility` semantics differ (a binary outcome's "daily vol" is not a
return stddev). The VaR leg may need a PM-specific volatility proxy, or
be left disabled (`dailyVarLimit = 0`) for the MVP and the gross cap
relied on. Decide this with a counter-example pass like
`docs/var-audit-2026-04-23.md`.

### Gate R — resolution risk (NEW gate)

PM-specific failure modes perps don't have: ambiguous/oracle-manipulated
resolution, and no time to exit before lock. New gate:

```lean
-- Veritas/Gates/ResolutionGate.lean  (NEW)
def minTrustTier : Nat := 2
def minSecondsToResolution : Nat := 3600

def checkResolution (p : TradeProposal) : Verdict :=
  if p.resolutionTrust < minTrustTier then
    .Reject ["resolution_source_below_trust_threshold"]
  else if p.secondsToResolution < minSecondsToResolution then
    .Reject ["too_close_to_resolution"]
  else .Approve
```

This is a strict gate (Approve/Reject only — no resize), so its
soundness theorem is a clean implication (see §4). It composes into the
certificate the same way the other gates do.

**Certificate cost:** `Certificate` (`Veritas/Gates/Types.lean`) is
currently a fixed 3-gate record. Two options:

- **(A) Add a fourth gate field** `gateR : Verdict` and a
  `marketType`-aware `approves`. Cleanest, but touches the certificate
  schema, `certificate_soundness`, the CLI emitter, `bridge.py`,
  `schemas.py`, and the attestation payload shape (which is versioned —
  would bump `schema_version`).
- **(B) MVP: fold resolution checks into Gate 1** as additional reject
  codes on the PM path, ship the standalone gate in a follow-up slice.
  Zero schema churn. **Recommended for the first slice.**

### Gate C — calibration (OPTIONAL, reuse Reliability)

Gate 2 already consumes calibration via the Beta posterior. A separate
*hard* calibration gate ("reject any bet from an agent whose posterior
sample on this category is too thin / too poorly calibrated") is a thin
wrapper over `BetaPosterior` and `posteriorMean_bounded`
(`Veritas/Learning/Reliability.lean`). Defer to a later slice; note it
here so the registry/gate design leaves room.

## 4. Theorem list

Legend: **R** = reused unchanged · **R\*** = new theorem, proof reuses
an existing one almost verbatim · **N** = genuinely new.

| Theorem | Status | Notes |
|---|---|---|
| `verifySignal_approve_implies_consistent` | **R** | Generic over registry; PM strategy covered for free. |
| `kellyFraction_nonneg`, `kellyFraction_mono` | **R** | The crux. Already proved for arbitrary `winLossRatio`. |
| `positionSizePM_nonneg` | **R\*** | Mirror of `positionSize_fromPosterior_nonneg`; uses `kellyFraction_nonneg`. |
| `positionSizePM_capped` | **R\*** | Mirror of `..._capped`; same `exploitationCap`. |
| `positionSizePM_zero_at_no_edge` | **R\*** | Cutoff is now `marketPrice`, not `1/2`; otherwise identical shape. |
| `positionSizePM_monotone_in_successes` | **R\*** | Mirror of `..._monotone_in_successes`; reuses `posteriorMean_monotone_in_successes` + `kellyFraction_mono`. |
| `positionSizePM_le_marketPrice_implies_zero` | **N** | New economic contract: never bet when your estimate doesn't beat the price. (Equivalent to the no-edge theorem; state it in PM language for the certificate.) |
| `checkConstraintsPM_resize_respects_ceiling` etc. | **R\*** | Mirror of the four `checkConstraints_*` theorems with the sizer swapped. |
| `checkPortfolio_*` (all 7) | **R** | Gate 3 unchanged. |
| `checkResolution_approve_implies_trusted` | **N** | `checkResolution p = .Approve → p.resolutionTrust ≥ minTrustTier ∧ p.secondsToResolution ≥ minSecondsToResolution`. Trivial by `unfold`/cases. |
| `certificate_soundness` (+ 3 final-within-* ) | **R / R\*** | **R** if going with Gate-R option B (fold into Gate 1). **R\*** (restate over 4 gates) if option A. |
| `reliabilityUpdate_*`, `posteriorMean_*`, `pessimisticMean_*` | **R** | The calibration substrate is untouched. |

Net new proof burden for the MVP: ~6 theorems, of which 5 are
near-mechanical mirrors of existing perp theorems and 1
(`checkResolution_*`) is trivial.

## 5. Reuse map — existing code → PM slice

| Existing asset (file) | Reuse |
|---|---|
| `Veritas/Finance/Kelly.lean` — `kellyFraction`, 2 thms | **Reused verbatim.** Pass real odds `(1−p)/p`. |
| `Veritas/Finance/PositionSizing.lean` — sizer + constants + 7 thms | **Templated.** New `PositionSizingPM.lean` copies structure; constants reused. |
| `Veritas/Learning/Reliability.lean` — `BetaPosterior`, `posteriorMean`, `updateReliability`, 11 thms | **Reused verbatim.** Calibration substrate is market-agnostic. |
| `Veritas/Gates/SignalGate.lean` — `verifySignal`, soundness thm | **Reused verbatim.** Registry-generic. |
| `Veritas/Strategy/Registry.lean` — `Strategy`, `allStrategies`, dispatch | **Extended.** Add `prob_edge`; add `marketType` filter. |
| `Veritas/Strategy/FundingReversion.lean` | **Template** for `ProbEdge.lean`. |
| `Veritas/Gates/ConstraintGate.lean` — `checkConstraints` + 4 thms | **Templated** into `checkConstraintsPM`. |
| `Veritas/Gates/PortfolioGate.lean` — `checkPortfolio` + 7 thms | **Reused** (validate VaR/vol semantics). |
| `Veritas/Gates/Types.lean` — `TradeProposal`, `AccountConstraints`, `Verdict`, `Certificate` | **Extended** (new optional fields; defaults preserve perp behavior). |
| `Veritas/Types.lean` — `Direction`, `MarketSnapshot`, `Signal` | **Extended.** Add `MarketType`; add PM fields to snapshot. |
| `Veritas/Main.lean` — CLI dispatch | **Extended.** New `check-constraints-pm` / extend `emit-certificate-ex`. |
| `python/schemas.py` — dataclasses | **Extended.** New `TradeProposal` fields (defaults keep wire back-compat). |
| `python/bridge.py` — `emit_certificate` arg packing | **Extended.** Append PM args. |
| `python/verifier.py` — orchestration | **Extended.** Route by `market_type`. |
| `python/attestation.py` — signing | **Reused.** Option-A 4-gate certificate bumps `schema_version`; option B keeps v2. |
| `python/api/theorem_registry.py` | **Extended.** Register the new PM theorems so `/verify/theorems` surfaces them. |
| Tests: `test_gates.py`, `test_bypass_invariant.py`, `test_loop.py` | **Extended.** Add PM gate cases; bypass-invariant rules unchanged. |

## 6. Wire / certificate additions

New `TradeProposal` fields (all defaulted → existing perp callers
unaffected): `market_type` (`"perp"`/`"binary_pm"`, default `"perp"`),
`market_price`, `estimated_prob`, `resolution_trust`,
`seconds_to_resolution`.

Optional certificate enrichment (sells the "verifiable probability"
story): add to the signed body an `attested_probability` and a
`methodology_hash` (sha256 of the declared estimation method). Because
the attestation payload is versioned, this is a `schema_version` bump,
not an edit to v2 — see `python/attestation.py`'s forward-compat
contract.

## 7. Slice plan (each leaves `lake build` sorry-free + `pytest` green)

1. **Types + Kelly proof of concept.** Add `MarketType` and PM fields
   (defaulted); write `calculatePositionSizeFromPosteriorPM` + its 4
   theorems. No wiring yet. *Proves the core thesis in isolation.*
2. **Gate 1 PM strategy.** `ProbEdge.lean` + registry entry + filter.
   Reuses the Gate-1 soundness theorem.
3. **Gate 2 PM dispatch.** `checkConstraintsPM` + CLI + bridge + a PM
   path in `verifier.py`; `test_gates.py` PM cases.
4. **Resolution checks (option B).** Fold resolution reject-codes into
   the PM Gate-1 path; `checkResolution` + trivial theorem as a pure
   function used inside it.
5. **Certificate enrichment + paper.** `attested_probability` /
   `methodology_hash` (schema bump); a short paper/demo preset showing
   a real signed PM verdict. Reuses the whole `web/build_static_demo.py`
   gallery pipeline.

A standalone Gate R (option A) and the calibration gate (Gate C) are
post-MVP slices.

## 8. Honest gaps / risks

- **Gate 1 economics are perp-specific today.** The *machinery* is
  reused, but a credible PM product needs real estimation strategies
  (base rates, news, polls), which is research, not formalization.
- **VaR/volatility semantics** don't transfer cleanly to bounded binary
  payoffs (§3, Gate 3). MVP should likely disable the VaR leg and lean
  on the gross-exposure cap until a PM vol proxy is audited.
- **Market price is a moving target.** The certificate binds to the
  `market_price` at request time via the existing request-digest; a
  caller must re-verify if the book moved (this is already the
  `request_digest` pin's job — no new mechanism, but document it).
- **TAM is smaller than crypto perps**, traded off against a cleaner
  verification story and a more compliance-friendly venue (Kalshi is
  CFTC-regulated).

---

*Reuse summary: ~1 new strategy file, ~1 new sizer file, ~6 new
theorems (5 mechanical mirrors + 1 trivial), a handful of defaulted
fields, and additive wiring. The three-gate kernel, the Kelly theory,
the Bayesian calibration layer, the attestation/signing path, and the
demo pipeline are all reused.*
