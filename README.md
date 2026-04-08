# Veritas

> Trust infrastructure for agent-native finance.

A trading agent on Hyperliquid that **knows what it's betting on**, **monitors whether the bet still holds**, and **gets smarter every time it's wrong**.

Unlike existing trading bots — static rule engines with no intelligence, or LLM black boxes that can't explain themselves — Veritas enforces assumption-first trading. Every trade has an explicit, falsifiable hypothesis. Every exit is categorized. Every outcome updates the agent's understanding.

## Quickstart

```bash
git clone https://github.com/[you]/veritas && cd veritas
pip install -r requirements.txt
cp config.example.toml config.toml
# Edit config.toml: add your Hyperliquid testnet private key
python -m veritas.main
```

## v0.1 Scope

- **One exchange**: Hyperliquid (testnet only)
- **One pair**: BTC-USDC perpetual
- **One strategy**: Funding rate mean reversion
- **One loop**: Observe → Decide → Declare → Size → Execute → Monitor → Exit → Learn

## How It Works

```
1. Observe   — fetch BTC funding rate, price, positions from Hyperliquid
2. Decide    — signal when funding rate hits extreme levels
3. Declare   — record the explicit assumption being bet on
4. Size      — scale position with assumption's historical reliability
5. Execute   — open position on Hyperliquid testnet
6. Monitor   — check every minute: does the assumption still hold?
7. Exit      — close when assumption confirmed, broken, or hard stop hit
8. Learn     — update assumption reliability from the outcome
```

Every trade is logged with its assumptions and exit reason. The assumption library persists across restarts — the agent improves over time.

## Architecture

```
veritas/
├── main.py         # Eight-step loop orchestration
├── observer.py     # Market data from Hyperliquid
├── decider.py      # Entry signal logic
├── extractor.py    # Assumption declaration
├── checker.py      # Historical reliability lookup
├── sizer.py        # Reliability-based position sizing
├── executor.py     # Order execution (open/close)
├── monitor.py      # Live assumption monitoring
├── learner.py      # Post-trade assumption update
└── journal.py      # SQLite persistence + JSONL logs
```

## Key Invariants

1. Every trade has an explicit assumption declaration — no black-box orders
2. Every exit is categorized: `assumption_met` / `assumption_broke` / `stop_loss`
3. Every trade updates the assumption library — persistence survives restarts
4. Hard stop loss always active — the last line of defense

## Verification Status

The Lean 4 core (`Veritas/`) builds with **zero `sorry`**. Every stated theorem has a proof.

| Module | Theorem | Status | Notes |
|--------|---------|--------|-------|
| `Finance/PositionSizing` | `positionSize_nonneg` | Proved | |
| `Finance/PositionSizing` | `positionSize_capped` | Proved | |
| `Finance/PositionSizing` | `positionSize_monotone_in_reliability` | Proved | |
| `Finance/PositionSizing` | `positionSize_zero_at_no_edge` | Proved | |
| `Finance/Kelly` | `kellyFraction_nonneg` | Proved | |
| `Finance/Kelly` | `kellyFraction_mono` | Proved | |
| `Strategy/ExitLogic` | `exitReason_exhaustive` | Proved | Pure case split, no axioms |
| `Learning/Reliability` | `reliabilityUpdate_monotone_on_wins` | Proved | Originally false without `wins ≤ total`; invariant now enforced in the type |
| `Learning/Reliability` | `reliabilityUpdate_bounded` | Proved | Same — `ReliabilityStats` carries the proof |

### What we trust

All proofs above the `ExitLogic` and `Reliability` module are axiom-free or use only Lean builtins. The `Finance/` proofs depend on **20 axioms** about IEEE 754 `Float` arithmetic in [`Finance/FloatAxioms.lean`](Veritas/Finance/FloatAxioms.lean):

| Category | Count | Soundness |
|----------|-------|-----------|
| Ordering (`le_refl`, `le_trans`, totality, etc.) | 7 | **Exact** — IEEE 754 comparison is hardware-exact for non-NaN values |
| Literal equality (`0.0 = 0`) | 1 | **Exact** — both represent IEEE 754 positive zero |
| Sign preservation (`mul_nonneg`, `div_nonneg`) | 2 | **Exact** — IEEE 754 sign bit is computed exactly |
| `Nat.toFloat` (nonneg, positivity, monotonicity) | 3 | **Exact** up to 2^53 (integer-exact range of binary64) |
| Arithmetic monotonicity (`sub_le`, `mul_le`, `div_le`, etc.) | 7 | **Rounding-dependent** — holds when rounding does not reverse the inequality |

The 7 rounding-dependent axioms are the honest gap. They assume that if the exact real-valued result satisfies `a ≤ b`, the IEEE 754 rounded result preserves the direction. This is not universally true for adversarial Float inputs, but it holds for the magnitudes Veritas operates on (probabilities in [0, 1], small integer counters, Kelly fractions). We accept this as a pragmatic modelling assumption. See the doc comment in `FloatAxioms.lean` for the full rationale.

**When Lean or Mathlib ships a `Float` proof library, every axiom in this file should be replaced with a library lemma and deleted.**

## Status

**v0.1** — Scaffold complete, implementation in progress.
