# Changelog

All notable changes to Veritas that affect callers (HTTP / MCP /
SDK / CLI surfaces, attestation schema, theorem registry).

Internal refactors and documentation-only commits are not listed.

## v0.4.0 — 2026-04-23

### Changed — Gate 2 reliability input (Bayesian migration)

Gate 2's `calculatePositionSize (equity, reliability, sampleSize)`
has been retired in favor of
`calculatePositionSizeFromPosterior (equity, BetaPosterior)`. The
ceiling is now driven by a Beta-posterior point estimate instead of
a frequentist `wins / total` ratio.

**`AccountConstraints` wire shape.** The `reliability : Rat` and
`sampleSize : Nat` fields have been removed; four Bayesian fields
replace them:

```
successes   : Nat  = 0
failures    : Nat  = 0
priorAlpha  : Rat  = 1
priorBeta   : Rat  = 1
```

Default priors are the uniform `Beta(1, 1)` (Laplace smoothing).
Cold-start behavior (`successes = failures = 0`) is byte-identical
to the retired frequentist input: posterior mean = 1/2, exploration
phase, 1% equity ceiling.

**Behavior drift summary.**

| Sample size               | Posterior mean vs reliability | Gate 2 sizing drift |
| ------------------------- | ----------------------------- | ------------------- |
| 0                         | exact match (both 1/2)        | none                |
| 20 (reliability=0.8)      | 17/22 ≈ 0.773 vs 0.800         | ~3% more conservative |
| 100 (reliability=0.80)    | 81/102 ≈ 0.794 vs 0.800        | <1% more conservative |
| ≥ 1000                    | indistinguishable              | negligible          |

### Changed — HTTP wire (backward compatibility shim)

`POST /verify/proposal` and siblings **still accept** the legacy
`reliability : float` and `sample_size : int` fields. Pydantic's
`ConstraintsIn` translates them into `(successes, failures)` at
validation time using a uniform `Beta(1, 1)` prior. A
`DeprecationWarning` fires **once per process** the first time any
caller submits a legacy field.

**Removal scheduled for v0.5.** The shim is a transition period,
not a permanent contract. Migrate HTTP callers now:

```diff
- "constraints": {"reliability": 0.80, "sample_size": 20, ...}
+ "constraints": {"successes": 16, "failures": 4, ...}
```

Optional priors `prior_alpha` and `prior_beta` default to `1.0`.

### Changed — MCP wire (clean migration, no shim)

The `verify_proposal` MCP tool's `inputSchema` has dropped
`reliability` / `sample_size` and added `successes` / `failures` /
`prior_alpha` / `prior_beta`. No backward compatibility on the MCP
surface — tighter product scope. MCP callers must migrate before
upgrading to v0.4.0.

### Changed — CLI wire (no shim)

The `veritas-core` binary's `check-constraints`,
`emit-certificate-ex`, and `size` subcommands take the Bayesian
argument layout directly:

```
veritas-core size <equity> <successes> <failures> <prior_alpha> <prior_beta>

veritas-core check-constraints <dir> <notional> <equity>
    <successes> <failures> <prior_alpha> <prior_beta>
    <max_leverage> <max_pos_frac> <stop_pct>
```

The dead-code `emit-certificate` (non-ex) subcommand has been
removed; `emit-certificate-ex` is the sole path.

### Removed

- Five frequentist `positionSize_*` theorems and their function
  `calculatePositionSize`.
- Two slice-3 `checkConstraintsBayesian_*` theorems (absorbed into
  `checkConstraints_*` — see below).
- `AccountConstraints.reliability` / `.sample_size` fields (Lean
  and Python).
- `emit-certificate` CLI subcommand (dead code).

### Added

- `BetaPosterior` type + `posteriorMean` + three foundational
  theorems (`_bounded`, `_monotone_in_successes`,
  `_uniform_prior_empty`).
- `calculatePositionSizeFromPosterior` + four theorems (`_nonneg`,
  `_capped`, `_zero_at_no_edge`, `_monotone_in_successes`).
- `AccountConstraints.posterior` accessor deriving a
  `BetaPosterior` from the new fields.

### Theorem registry

**Count: 39 → 33.** Rewritten entries (now express Bayesian
semantics): `checkConstraints_approve_within_ceiling`,
`_resize_respects_ceiling`, `_approve_implies_proposal_nonneg`,
`_resize_nonneg`,
`certificate_approve_final_within_gate2_ceiling`.

### Attestation

- `VERITAS_VERSION` advertised on `/verify/pubkey` moves from
  `"0.3.4"` to `"0.4.0"`.
- `schema_version` (signed-payload shape) stays at `2` — no change
  to the attestation wire.
- `theorem_registry_sha` changes substantively (statement rewrites
  + theorem additions / removals). Any caller pinning a v0.3
  `theorem_registry_sha` **must re-pin** after reviewing the
  narrowed / rebased Gate-2 semantics.
- `build_sha` changes. This release modifies decision-path code,
  unlike the earlier v0.3.4 docstring-only VaR correction where
  `build_sha` was byte-identical.

### Migration guidance

See `docs/migration-plan-2026-04-23.md` for the full migration
design (decisions, trade-offs, slice cut). Summary actions per
surface:

| Surface         | Required action                                                           | v0.5 deadline?             |
| --------------- | ------------------------------------------------------------------------- | -------------------------- |
| Python dataclass | Replace `reliability=/sample_size=` kwargs with `successes=/failures=`    | yes — shim absent          |
| HTTP body        | Migrate JSON to `{"successes": ..., "failures": ..., "prior_alpha": ..., "prior_beta": ...}` | yes — legacy shim removed |
| MCP tool call    | Use the new input keys (`successes`, `failures`, `prior_alpha`, `prior_beta`) | already required          |
| CLI user         | New positional arg layout                                                 | already required          |
| Trust pin        | Re-fetch `/verify/pubkey`; re-pin `theorem_registry_sha` and `build_sha` | required now               |

## Older releases

Releases before v0.4.0 are tracked only in the commit log. The
slice-sized release cadence this project uses keeps `git log
--oneline` readable as a changelog substitute up to this point.
Starting with v0.4.0 we maintain this file for caller-visible
changes only.
