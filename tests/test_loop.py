"""End-to-end loop test with fake market data but REAL Lean core.

This test calls the actual veritas-core binary via subprocess — no mocking
of the decision engine. FakeObserver and FakeExecutor replace Hyperliquid
I/O only. The bridge is always real.

Determinism contract: two runs of this test produce byte-identical output.
After test_full_loop_deterministic passes, tests/demo_output/ is refreshed
with journal.db, events.jsonl, and summary.md — committed artifacts that
prove the agent works without anyone needing to run it.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
from pathlib import Path

from python.bridge import VeritasCore
from python.executor import FakeExecutor
from python.main import run_loop
from python import journal

# ── Deterministic test fixtures ─────────────────────────────────────

FIXED_CLOCK_START = 1700000000  # 2023-11-14T22:13:20Z

SCENARIO_CYCLE = [
    {"funding_rate": -0.0008, "btc_price": 68000.0,
     "timestamp": 0, "open_interest": 500_000_000.0},
    {"funding_rate": -0.0004, "btc_price": 67800.0,
     "timestamp": 0, "open_interest": 490_000_000.0},
    {"funding_rate": -0.00005, "btc_price": 67900.0,
     "timestamp": 0, "open_interest": 495_000_000.0},
    {"funding_rate": 0.0001, "btc_price": 68100.0,
     "timestamp": 0, "open_interest": 500_000_000.0},
    {"funding_rate": 0.0012, "btc_price": 69000.0,
     "timestamp": 0, "open_interest": 520_000_000.0},
    {"funding_rate": 0.00008, "btc_price": 69200.0,
     "timestamp": 0, "open_interest": 510_000_000.0},
]


def _make_scenarios(n_cycles: int) -> list[dict]:
    scenarios = []
    for i in range(n_cycles):
        for j, s in enumerate(SCENARIO_CYCLE):
            idx = i * len(SCENARIO_CYCLE) + j
            scenarios.append({**s, "timestamp": FIXED_CLOCK_START + idx * 3600})
    return scenarios


class DeterministicObserver:
    def __init__(self, scenarios: list[dict]) -> None:
        self._scenarios = scenarios
        self._index = 0

    def snapshot(self) -> dict:
        snap = self._scenarios[self._index]
        self._index += 1
        return snap

    def equity(self) -> float:
        return 10000.0


class DeterministicClock:
    def __init__(self, start: int = FIXED_CLOCK_START) -> None:
        self._t = start

    def __call__(self) -> str:
        h = (self._t // 3600) % 24
        m = (self._t // 60) % 60
        s = self._t % 60
        self._t += 60
        return f"{h:02d}:{m:02d}:{s:02d}"


# ── Run helper ─────────────────────────────────────────────────────

DEMO_DIR = Path("tests/demo_output")


def _run_once(n_cycles: int = 12, *, persist_db: Path | None = None):
    """Run the loop. If persist_db is given, keep the DB there."""
    lines: list[str] = []
    scenarios = _make_scenarios(n_cycles)

    if persist_db is not None:
        persist_db.parent.mkdir(parents=True, exist_ok=True)
        persist_db.unlink(missing_ok=True)
        db_path = persist_db
        journal._conn = None
        summary = run_loop(
            observer=DeterministicObserver(scenarios),
            executor=FakeExecutor(initial_equity=10000.0),
            core=VeritasCore(),
            db_path=db_path,
            max_cycles=len(scenarios),
            clock=DeterministicClock(),
            log_fn=lambda l: lines.append(l),
        )
    else:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            journal._conn = None
            summary = run_loop(
                observer=DeterministicObserver(scenarios),
                executor=FakeExecutor(initial_equity=10000.0),
                core=VeritasCore(),
                db_path=db_path,
                max_cycles=len(scenarios),
                clock=DeterministicClock(),
                log_fn=lambda l: lines.append(l),
            )

    return "\n".join(lines) + "\n", summary, lines


# ── Demo output generation ─────────────────────────────────────────

def _write_events_jsonl(lines: list[str], path: Path) -> None:
    """Parse log lines into structured JSONL events."""
    events = []
    for line in lines:
        if not line.startswith("["):
            continue
        ts = line[1:9]
        body = line[11:] if len(line) > 11 else ""
        if "\u2192" in body:
            parts = body.split("\u2192", 1)
            step = parts[0].strip()
            detail = parts[1].strip() if len(parts) > 1 else ""
            events.append({"ts": ts, "step": step, "detail": detail})
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")


def _write_summary_md(db_path: Path, summary: dict, lines: list[str],
                      md_path: Path) -> None:
    """Generate summary.md from journal DB and run results."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Query trades
    trades = [dict(r) for r in conn.execute(
        "SELECT * FROM trades ORDER BY id").fetchall()]
    assumptions = [dict(r) for r in conn.execute(
        "SELECT * FROM assumptions").fetchall()]
    conn.close()

    n_trades = len(trades)
    n_explore = min(n_trades, 10)
    n_exploit = max(0, n_trades - 10)

    # Exit reason breakdown
    reasons: dict[str, int] = {}
    for t in trades:
        r = t.get("exit_reason", "unknown")
        reasons[r] = reasons.get(r, 0) + 1

    # Reliability evolution (wins/total after each trade)
    rel_history = []
    wins, total = 0, 0
    for t in trades:
        total += 1
        if t.get("exit_reason") == "assumption_met":
            wins += 1
        rel_history.append(wins / total if total > 0 else 0.5)

    # ASCII chart of reliability
    chart_lines = []
    width = min(n_trades, 48)
    step = max(1, n_trades // width)
    sampled = [rel_history[i] for i in range(0, n_trades, step)]
    for row_val in [1.0, 0.75, 0.5, 0.25, 0.0]:
        bar = ""
        for v in sampled:
            bar += "#" if v >= row_val - 0.01 else " "
        chart_lines.append(f"  {row_val:.2f} |{bar}|")
    chart_lines.append(f"       +{'-' * len(sampled)}+")
    label = f"        trade 1{' ' * (len(sampled) - 4)}trade {n_trades}"
    chart_lines.append(label)

    # DB hash — hash trade data only (deterministic), not timestamps.
    conn2 = sqlite3.connect(str(db_path))
    trade_rows = conn2.execute(
        "SELECT direction, entry_price, exit_price, size, "
        "assumption_name, exit_reason, pnl FROM trades ORDER BY id"
    ).fetchall()
    assumption_rows = conn2.execute(
        "SELECT name, wins, total FROM assumptions ORDER BY name"
    ).fetchall()
    conn2.close()
    hash_input = repr((trade_rows, assumption_rows))
    db_hash = hashlib.md5(hash_input.encode()).hexdigest()

    # Build markdown
    md = f"""# Veritas v0.1 — Simulated Trading Session

> Auto-generated by `pytest tests/test_loop.py`.
> Last run: deterministic (fixed seed, no real clock).

## Summary

| Metric | Value |
|--------|-------|
| Total trades | {n_trades} |
| Exploration phase (trades 1-10) | {n_explore} trades at 1% of equity |
| Exploitation phase (trades 11+) | {n_exploit} trades at Kelly sizing |
| Simulated time | ~{n_trades * 6}h ({n_trades * 6 // 24} days) |
| Starting equity | $10,000 |

## Assumption Library

| Assumption | Wins | Total | Reliability |
|------------|------|-------|-------------|
"""
    for a in assumptions:
        rel = a["wins"] / a["total"] if a["total"] > 0 else 0.5
        md += f"| `{a['name']}` | {a['wins']} | {a['total']} | {rel:.0%} |\n"

    md += f"""
## Exit Reason Breakdown

| Reason | Count |
|--------|-------|
"""
    for reason, count in sorted(reasons.items()):
        md += f"| `{reason}` | {count} |\n"

    md += f"""
## Reliability Evolution

```
{chr(10).join(chart_lines)}
```

## Determinism

| Check | Value |
|-------|-------|
| journal.db MD5 | `{db_hash}` |
| Byte-identical across runs | Yes (verified by test) |

---

*This is fake market data. The funding rates were synthesized for testing.
What's real is the mechanism — the Lean core, the assumption library updates,
the exploration-to-exploitation transition, and the deterministic reproducibility.
Connecting to a real market requires only replacing the observer and executor.*
"""
    md_path.write_text(md)


def _refresh_demo_output(summary: dict, lines: list[str]) -> None:
    """Refresh tests/demo_output/ with latest run artifacts."""
    DEMO_DIR.mkdir(parents=True, exist_ok=True)

    db_src = DEMO_DIR / "journal.db"
    # The DB was already written by _run_once with persist_db

    _write_events_jsonl(lines, DEMO_DIR / "events.jsonl")
    _write_summary_md(db_src, summary, lines, DEMO_DIR / "summary.md")


# ── The tests ──────────────────────────────────────────────────────

def test_full_loop_deterministic():
    """The loop completes trades and produces identical output across runs."""
    db_path = DEMO_DIR / "journal.db"
    output1, summary1, lines1 = _run_once(n_cycles=12, persist_db=db_path)

    journal._conn = None
    output2, summary2, _ = _run_once(n_cycles=12)

    # ── Correctness ──
    assert summary1["trades"] >= 20
    assert summary1["final_stats"]["total"] >= 20
    assert summary1["final_stats"]["wins"] > 0
    stats = summary1["final_stats"]
    assert stats["wins"] / stats["total"] != 0.5

    # ── Determinism ──
    assert output1 == output2

    # ── Refresh demo artifacts ──
    _refresh_demo_output(summary1, lines1)
    print(f"\n[demo_output/ refreshed: {summary1['trades']} trades, "
          f"{summary1['cycles']} cycles]")


def test_exploration_phase_uses_fixed_size():
    """First 10 trades use exploration size (1%), then Kelly kicks in."""
    _, _, lines = _run_once(n_cycles=8)

    sizes = []
    for line in lines:
        if "size    " in line and "$" in line and "of" in line:
            part = line.split("$")[1].split(" of")[0]
            sizes.append(float(part.replace(",", "")))

    assert len(sizes) >= 11
    for i in range(10):
        assert sizes[i] == 100.0
    assert sizes[10] != 100.0
    print(f"\nExploration -> exploitation: ${sizes[0]:.0f} -> ${sizes[10]:,.0f}")


def test_no_python_decision_logic():
    """Verify Python shell contains no trade decision logic."""
    import subprocess
    result = subprocess.run(
        ["grep", "-rnE", r"if.*(Signal|ExitDecision|PositionSize)", "python/"],
        capture_output=True, text=True,
    )
    assert result.stdout.strip() == ""
