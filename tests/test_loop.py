"""End-to-end loop test with fake market data but REAL Lean core.

This test calls the actual veritas-core binary via subprocess — no mocking
of the decision engine. FakeObserver and FakeExecutor replace Hyperliquid
I/O only. The bridge is always real.

Determinism contract: two runs of this test produce byte-identical
demo_output.txt. This validates Veritas's reproducibility claim.
"""

import tempfile
from pathlib import Path

from python.bridge import VeritasCore
from python.executor import FakeExecutor
from python.main import run_loop
from python import journal

# ── Deterministic test fixtures ─────────────────────────────────────

FIXED_CLOCK_START = 1700000000  # 2023-11-14T22:13:20Z

# 6-scenario cycle: signal → hold → exit → calm → signal → exit
# Repeats to generate many trades.
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
    """Generate n_cycles worth of scenarios with proper timestamps."""
    scenarios = []
    for i in range(n_cycles):
        for j, s in enumerate(SCENARIO_CYCLE):
            idx = i * len(SCENARIO_CYCLE) + j
            scenarios.append({
                **s,
                "timestamp": FIXED_CLOCK_START + idx * 3600,
            })
    return scenarios


class DeterministicObserver:
    """Observer with fixed scenarios and no time.time() dependency."""

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
    """Fake clock that increments from a fixed start."""

    def __init__(self, start: int = FIXED_CLOCK_START) -> None:
        self._t = start

    def __call__(self) -> str:
        h = (self._t // 3600) % 24
        m = (self._t // 60) % 60
        s = self._t % 60
        self._t += 60
        return f"{h:02d}:{m:02d}:{s:02d}"


# ── The tests ──────────────────────────────────────────────────────

DEMO_OUTPUT_PATH = Path("tests/demo_output.txt")


def _run_once(n_cycles: int = 12) -> tuple[str, dict, list[str]]:
    """Run the full loop once, return (captured_output, summary, lines)."""
    lines: list[str] = []

    def capture(line: str) -> None:
        lines.append(line)

    scenarios = _make_scenarios(n_cycles)

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
            log_fn=capture,
        )

    return "\n".join(lines) + "\n", summary, lines


def test_full_loop_deterministic():
    """The loop completes trades and produces identical output across runs."""
    output1, summary1, _ = _run_once(n_cycles=12)
    output2, summary2, _ = _run_once(n_cycles=12)

    # ── Correctness assertions ──
    assert summary1["trades"] >= 20, (
        f"Expected at least 20 completed trades, got {summary1['trades']}"
    )
    assert summary1["final_stats"] is not None
    assert summary1["final_stats"]["total"] >= 20
    assert summary1["final_stats"]["wins"] > 0

    # Reliability should differ from default 0.5
    stats = summary1["final_stats"]
    reliability = stats["wins"] / stats["total"] if stats["total"] > 0 else 0.5
    assert reliability != 0.5, "Reliability should have changed from default"

    # ── Determinism assertion ──
    assert output1 == output2, (
        "Two runs produced different output — determinism violated."
    )

    # ── Write demo output ──
    DEMO_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEMO_OUTPUT_PATH.write_text(output1)
    print(f"\n[demo_output.txt written: {len(output1)} bytes, "
          f"{summary1['trades']} trades, "
          f"{summary1['cycles']} cycles]")


def test_exploration_phase_uses_fixed_size():
    """First 10 trades use exploration size (1%), then Kelly kicks in."""
    # Run enough cycles to get past exploration (10 trades) + a few more
    _, _, lines = _run_once(n_cycles=8)

    # Extract position sizes from "size → $X of $Y" lines
    sizes = []
    for line in lines:
        if "size    " in line and "$" in line and "of" in line:
            # Parse "$100.00 of $10,000"
            part = line.split("$")[1].split(" of")[0]
            sizes.append(float(part.replace(",", "")))

    assert len(sizes) >= 11, f"Need at least 11 trades, got {len(sizes)}"

    # First 10 trades: exploration phase → $100 (1% of $10,000)
    for i in range(10):
        assert sizes[i] == 100.0, (
            f"Trade {i+1} should be $100 (exploration), got ${sizes[i]}"
        )

    # Trade 11+: exploitation phase → different size (Kelly-based)
    assert sizes[10] != 100.0, (
        f"Trade 11 should use Kelly sizing, but got ${sizes[10]} (still exploration?)"
    )
    print(f"\nExploration → exploitation transition verified:")
    print(f"  Trades 1-10: ${sizes[0]:.0f} each (exploration)")
    print(f"  Trade 11: ${sizes[10]:,.0f} (Kelly)")


def test_no_python_decision_logic():
    """Verify Python shell contains no trade decision logic."""
    import subprocess

    result = subprocess.run(
        ["grep", "-rnE", r"if.*(Signal|ExitDecision|PositionSize)", "python/"],
        capture_output=True, text=True,
    )
    assert result.stdout.strip() == "", (
        f"Python contains decision logic:\n{result.stdout}"
    )
