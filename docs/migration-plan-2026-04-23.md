# Gate 2 Bayesian Migration — Plan (2026-04-23)

**Status:** plan only; no code change yet. Written after v0.4 slice 3
(`6a7931e`) landed `checkConstraintsBayesian` with its two soundness
theorems, leaving the full Bayesian stack proved but unwired.

**Scope:** route Gate 2 through the Bayesian stack built in v0.4
slices 1–3, and retire the frequentist `reliability` / `sampleSize`
input path. Answers the six review questions below, proposes a
two-sub-slice cut, and enumerates the full blast radius.

---

## Q1. Gate 2 老定理的处理

**Options considered**

| Option                                     | Effect on registry                                            |
| ------------------------------------------ | ------------------------------------------------------------- |
| Migrate (delete frequentist, keep Bayesian) | Drops 5 frequentist `positionSize_*` + rewrites 2 Gate-2 soundness theorems against the new ceiling |
| Keep both (frequentist lives on as orphan) | 5 `positionSize_*` theorems keep proving but bind to nothing in dispatch — dead weight on the trust surface |
| Rename + redefine                           | Double the theorem count; every reader has to pick which family to trust |

**Recommended:** **Migrate (delete + rewrite).**

Concrete plan:

- **Delete** the frequentist sizer theorems:
  `positionSize_nonneg`, `positionSize_capped`,
  `positionSize_zero_at_no_edge`, `positionSize_explorationCapped`,
  `positionSize_monotone_in_reliability`.
- **Delete** the frequentist function `calculatePositionSize` itself.
  Its 3 Bayesian twins already cover the same guarantees.
- **Add one more Bayesian theorem** to preserve monotonicity:
  `positionSize_fromPosterior_monotone_in_successes` (adding successes
  to the posterior input never decreases the sizer's output).
  Analog of the retired `positionSize_monotone_in_reliability`.
- **Rewrite** the two Gate-2 soundness theorems to bind against the
  new ceiling:
  - `checkConstraints_approve_within_ceiling`:
    new conclusion `p.notionalUsd ≤ calculatePositionSizeFromPosterior c.equity c.posterior`
  - `checkConstraints_resize_respects_ceiling`: analog.
- **Delete** the duplicate `checkConstraintsBayesian_*` theorems
  added in slice 3 — once `checkConstraints` *is* the Bayesian
  path, those theorems become about a non-existent function. Their
  proofs land in the renamed `checkConstraints_*` under the same
  names.

**Net theorem-count change** (from 39):  
`–5 (frequentist) +1 (new monotone) –2 (slice-3 duplicates) +0 (rewrites in place) = –6 → 33.`

Simpler trust surface. Frequentist historical artifacts are gone —
what's left is exactly what Gate 2 actually does.

**Trade-off:** anyone who had linked to `positionSize_nonneg`
(e.g. in the paper) now has a dead link; the paper needs a companion
update. Low risk — the paper already points at
`Veritas/Finance/PositionSizing.lean` by file, not by theorem name.

---

## Q2. 新老 checkConstraints 关系

**Option A (default):** Bayesian becomes the only `checkConstraints`;
frequentist disappears.

- Pro: one code path, one soundness story.
- Pro: certificate-composition proofs stay monolithic.
- Con: wire-format break for callers who currently send `reliability`
  + `sample_size`.
- Mitigation: Python shim on the HTTP / MCP boundary translates
  legacy fields to a BetaPosterior; caller behavior is nearly
  identical post-mature-sample (small quantitative delta under
  Beta(1,1) smoothing — documented as a known refinement).

**Option B (evaluated):** Two coexist, `AccountConstraints` has both
field sets, Gate 2 routes by which is supplied.

- Pro: zero wire-format break.
- Con: `checkConstraints` gains a branch; soundness theorems split
  into two cases; `certificate_approve_final_within_gate2_ceiling`
  needs a disjunction in its conclusion (ceiling is either the
  frequentist one or the Bayesian one). Every downstream theorem
  that reads "the Gate-2 ceiling" now has to disambiguate.
- Con: same caller can get different sizing by accident (which fields
  they happened to set). Reliability of the trust surface drops.
- **Reject:** complexity cost vastly exceeds compat benefit since
  there are no production callers pinned to the old semantics.

**Option C (evaluated):** Bayesian lives as a separate Gate 4 /
opt-in extra check; Gate 2 stays deterministic frequentist.

- Pro: no breaking changes; the v0.3 "three gates" brand stays intact.
- Con: contradicts the v0.4 calibration thesis. The whole point is
  that the *primary* Gate 2 gets smarter; tucking Bayesian into an
  optional Gate 4 leaves Gate 2's known-bad small-sample behavior
  in place for everyone who doesn't opt in.
- Con: a Gate 4 that's parallel (not sequential in the cert
  pipeline) doesn't have a natural composition story. The composed
  soundness arc that v0.3 slices 6–8 built assumed sequential
  gates.
- **Reject:** wrong shape for the problem; Bayesian *is* the new
  reliability, not an extension.

**Recommended:** **A** (as the user defaulted). Below sections assume A.

---

## Q3. AccountConstraints schema migration

**Lean side (final target shape):**

```lean
structure AccountConstraints where
  equity : Rat
  maxPositionFraction : Rat
  maxLeverage : Rat
  stopLossPct : Rat
  -- Bayesian reliability inputs (replaces frequentist reliability+sampleSize)
  successes : Nat := 0
  failures : Nat := 0
  priorAlpha : Rat := 1
  priorBeta : Rat := 1
  -- (unchanged)
  dailyVarLimit : Rat := 0
  deriving Repr, Inhabited
```

- **New fields are optional with defaults.** A caller who passes
  nothing gets `successes = 0, failures = 0, Beta(1, 1)` — posterior
  mean = 1/2 and sampleSize = 0 → exploration phase → 1% of equity.
  **Byte-identical cold-start behavior** to v0.3, which is what we
  want.

**Python side (HTTP `ConstraintsIn` final shape):**

```python
class ConstraintsIn(BaseModel):
    equity: float = Field(gt=0)
    max_leverage: float = 1.0
    max_position_fraction: float = 0.25
    stop_loss_pct: float = 5.0
    daily_var_limit: float = Field(default=0.0, ge=0)
    # New canonical fields
    successes: int = Field(default=0, ge=0)
    failures: int = Field(default=0, ge=0)
    prior_alpha: float = Field(default=1.0, ge=0)
    prior_beta: float = Field(default=1.0, ge=0)
    # Deprecated — still accepted, translated in a model_validator
    reliability: float | None = Field(default=None, ge=0, le=1)
    sample_size: int | None = Field(default=None, ge=0)
```

**Legacy-caller translation (Python-side shim):**

If `reliability` and `sample_size` are set and `successes + failures == 0`:

```
successes = round(reliability * sample_size)
failures  = sample_size - successes
prior_alpha = 1, prior_beta = 1
```

This preserves **old behavior at large samples** exactly (posterior
mean ≈ reliability) and adds mild Bayesian smoothing at small
samples — which is the whole point.

**Old schema caller behavior (with no migration on their side):**

- HTTP POST `/verify/proposal` with old body shape still works; shim
  translates.
- SDK Python caller using `sdk.AccountConstraints(reliability=0.75,
  sample_size=20)` — **this will break** because the fields are
  gone from the schema. SDK users must migrate to
  `AccountConstraints(successes=15, failures=5)`. The SDK test
  suite will catch any missed fixture.

**Fixtures to update (enumerated):**

| File                             | Count | Migration         |
| -------------------------------- | ----- | ----------------- |
| `tests/test_loop.py`             | 5     | mechanical        |
| `tests/test_gates.py`            | 2     | mechanical        |
| `tests/test_attestation.py`      | 1     | mechanical        |
| `tests/test_sdk_surface.py`      | 4     | mechanical        |
| `python/sdk.py` (docstring example) | 1     | mechanical        |
| `python/mcp/server.py`           | 1     | trivial (MCP already tracks `wins`/`total` in its DB — just rename) |
| `python/api/routes/verify.py`    | 1     | converter change  |
| **Total**                        | **15** |                   |

All mechanical. Automated find-replace plus spot-check is sufficient.
No test-assertion changes needed as long as behavior is preserved
(which it is, by construction of the translation).

---

## Q4. `theorem_registry_sha` change

**Will it change?** Yes, substantively:

- 5 theorems deleted, 1 theorem added, 2 theorems rewritten, 2
  theorems renamed (slice-3 duplicates collapsed into the main
  `checkConstraints_*`), `certificate_approve_final_within_gate2_ceiling`
  **rewritten** because its conclusion now references
  `calculatePositionSizeFromPosterior`.
- Every `statement_natural_language` for affected theorems changes.
- Registry SHA is a function of canonical JSON of `THEOREMS`, so
  it changes.

**Version bump:** `VERITAS_VERSION` moves from `"0.3.4"` →
`"0.4.0"`. Rationale:
- Gate-2 ceiling behavior changes under the hood — a proposal's
  approved size can differ numerically from v0.3 on small samples
  even for the same inputs.
- Attestation `veritas_version` field surfaces this to callers.
- Per the forward-compat contract in `python/attestation.py`:
  version bumps on the *Veritas release* axis are independent of
  the attestation `schema_version`. `schema_version` stays at `2`
  (no change to the signed-payload shape).

**Pinned callers:**

- No production callers yet. This is the last cheap moment to
  rehearse the trust-update dance.
- Any caller that has stashed a `theorem_registry_sha` from v0.3
  should refetch `/verify/pubkey`, compare semantics, re-pin.

**CHANGELOG:** no `CHANGELOG.md` yet in the repo. Create one as part
of this migration with a single entry:

```
# Changelog

## v0.4.0 — 2026-04-XX
### Changed
- Gate 2 reliability input migrated from frequentist (reliability,
  sampleSize) to Bayesian (successes, failures, priorAlpha, priorBeta).
  Default Beta(1,1) prior preserves cold-start behavior; mature-
  sample sizing is nearly identical; small-sample sizing is more
  conservative (Laplace smoothing).
- theorem_registry_sha changes; any caller pinned to v0.3 must
  re-pin.
- AccountConstraints no longer carries `reliability` / `sampleSize`
  fields. Python schemas translate legacy inputs.
```

---

## Q5. Backward compatibility scope

**Counted touchpoints** (see Q3 table):

- **Lean:** 1 struct, 1 function redef, 5 theorem deletes, 4 theorem
  restatements, 1 new theorem, 4–5 CLI handler updates in Main.lean.
- **Python schema/API:** 1 dataclass (`AccountConstraints`), 1
  HTTP schema (`ConstraintsIn` + translator), 1 MCP schema +
  `_handle_verify_proposal`, 1 `_to_constraints` helper in
  `verify.py`.
- **Bridge:** 2 call-site signatures (`check_constraints`,
  `emit_certificate`).
- **SDK shim:** `python/sdk.py` re-exports AccountConstraints — no
  re-export change, but its docstring example needs field update.
- **Tests:** 15 fixture sites (enumerated above).

**Prep-slice option vs big-bang:**

| Approach           | Pros                                   | Cons                                                     |
| ------------------ | -------------------------------------- | -------------------------------------------------------- |
| **Prep slice first** (compat shim only; behavior unchanged) | Tiny reviewable step; later slice is pure structural migration | No user-visible change; feels like wasted ceremony; intermediate state where Python knows about posterior fields but Lean doesn't route them |
| **Big-bang**       | Single reviewable unit; no orphan state | ~300+ LOC of mechanical changes in one commit            |

**Recommended:** **Split into two sub-slices** (but *not* the
prep-slice route above). See Q6.

---

## Q6. Slice size control — recommended cut

**Proposed two-sub-slice cut:**

### v0.4 slice 4 (Lean-only migration + CLI shim)

**What lands:**

- `AccountConstraints` struct migrated: drop `reliability`,
  `sampleSize`; add `successes`, `failures`, `priorAlpha`,
  `priorBeta` with defaults.
- `checkConstraints` routed through
  `calculatePositionSizeFromPosterior` (constructs a BetaPosterior
  from the new fields).
- Gate-2 soundness theorems rewritten in place (`_approve_within_
  ceiling`, `_resize_respects_ceiling`).
- 5 frequentist `positionSize_*` theorems + `calculatePositionSize`
  function **deleted** from `Veritas/Finance/PositionSizing.lean`.
- `certificate_approve_final_within_gate2_ceiling` **rewritten**
  in `Veritas/Gates/Certificate.lean` (conclusion references the
  new sizer).
- 2 slice-3 `checkConstraintsBayesian_*` duplicates **deleted**
  (their proofs are now inside `checkConstraints_*`).
- 1 new theorem added: `positionSize_fromPosterior_monotone_in_successes`.
- `Veritas/Main.lean` CLI handlers: **accept BOTH old and new arg
  layouts** for `check-constraints` and `emit-certificate-ex`.
  The old `<rel> <sample>` pair is translated inside the handler
  to the new BetaPosterior form. This is the shim that keeps
  Python-side tests green without modifying a single Python file
  in this slice.
- Theorem registry: all affected entries edited in one commit.
- Lake build sorry-free; pytest 176/176 green (Python side still
  sends legacy args, CLI shim translates).
- `VERITAS_VERSION` bump → `"0.4.0"`.

**Why Lean can land first:** the CLI shim absorbs the mismatch.
Python code keeps sending `<rel> <sample>` and nothing on the
Python side moves. Lean has the new ceiling, new theorems, and a
translator at its boundary.

**Expected diff size:** ~350 LOC Lean (mostly edits), ~40 LOC
registry, zero Python. One commit.

### v0.4 slice 5 (Python-side modernization + shim removal)

**What lands:**

- `python/schemas.py` `AccountConstraints`: drop `reliability`,
  `sample_size`; add `successes`, `failures`, `prior_alpha`,
  `prior_beta`.
- `python/api/routes/verify.py` `ConstraintsIn`: add new fields
  primary; `reliability` / `sample_size` accepted as deprecated
  with `model_validator` translator. Log deprecation warning.
- `python/mcp/server.py`: update tool inputSchema + handler; MCP's
  own DB-side `wins`/`total` already gives us native posterior
  inputs.
- `python/bridge.py`: `check_constraints` / `emit_certificate` call
  sites send new args.
- `python/sdk.py` docstring example updated.
- `tests/`: 15 fixture sites migrated — mechanical search & replace
  (`reliability=X, sample_size=Y` → `successes=round(X*Y),
  failures=Y-round(X*Y)`).
- `Veritas/Main.lean`: **remove the CLI shim** added in slice 4;
  CLI now only accepts the new arg layout.
- `CHANGELOG.md`: new file (per Q4 draft).

**Expected diff size:** ~200 LOC Python + ~50 LOC Lean (shim
removal) + ~30 LOC test migration. One commit.

---

## Risks & mitigations

| Risk                                                              | Mitigation                                                 |
| ----------------------------------------------------------------- | ---------------------------------------------------------- |
| CLI shim in slice 4 becomes accidentally permanent                | Slice 5 removes it in the same review cycle; if slice 5 is ever postponed, add a `-- TODO(slice 5): remove shim` comment |
| `certificate_approve_final_within_gate2_ceiling` rewrite fails    | The structural proof is known (slice 6 recipe); failure mode is wrestling with Lean elaboration, not a conceptual gap |
| Test-fixture migration introduces off-by-one on round()           | Spot-check one fixture numerically; add a `_migrate_legacy_reliability` helper with its own unit test |
| Pre-existing caller pins registry SHA from v0.3                   | No production caller yet; this is the rehearsal |
| Gate 2 behavior drift on mature samples > acceptable              | Sampled check: `reliability=0.8, sample_size=100` → posterior mean `= 81/102 ≈ 0.794`. Drift is < 1%. Document in CHANGELOG |
| Gate 2 behavior drift on small samples causes test failures       | Existing tests use `sample_size=20, reliability=0.8` → posterior mean `(16+1)/(20+2) ≈ 0.773`. Call `positionSize_fromPosterior_zero_at_no_edge` — still above 0.5 cutoff, still exploitation phase, sizing changes slightly. No test asserts exact `allowed` value; **spot-check `test_gate2_approves_within_ceiling` + `test_gate2_resizes_when_above_ceiling` once slice 4 lands** to confirm |

---

## Rollback plan

- Slice 4 and slice 5 are independent commits. Reverting slice 5
  restores the legacy Python wire while keeping Lean migrated.
- Reverting slice 4 is a structural rollback of a 350-LOC commit;
  possible but heavy. `git revert 6a7931e<slice-4-sha>` backs out
  the struct change.
- Attestation `veritas_version` bump is observable by callers; a
  revert + re-release would need to bump to `"0.4.1"` (or whatever
  the fix is) to avoid version-reuse.

---

## Open question for the operator (needs answer before slice 4)

**Should the Python-side shim in slice 5 log a deprecation warning
for legacy `reliability` / `sample_size` callers, and for how long?**

Options:
- **Silent translation forever.** Permissive; invisible compat.
- **Warn on every call.** Fast push to migrate, noisy.
- **Warn once per process.** Standard Python deprecation pattern.
- **Warn + remove in v0.5.** Time-bounded; forces migration.

Default recommendation absent other input: **warn once per process,
removal scheduled for v0.5.** Standard Python convention.

---

## Decision to make

Approve the two-sub-slice plan (slice 4 Lean-only + shim,
slice 5 Python + shim removal), or redirect. Once approved, I start
slice 4.
