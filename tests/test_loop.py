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

SCENARIOS = [
    # Cycle 1: extreme negative funding → SHORT signal
    {"funding_rate": -0.0008, "btc_price": 68000.0,
     "timestamp": FIXED_CLOCK_START, "open_interest": 500_000_000.0},
    # Cycle 2: funding reverting → hold
    {"funding_rate": -0.0004, "btc_price": 67800.0,
     "timestamp": FIXED_CLOCK_START + 3600, "open_interest": 490_000_000.0},
    # Cycle 3: funding near zero → assumption met → exit
    {"funding_rate": -0.00005, "btc_price": 67900.0,
     "timestamp": FIXED_CLOCK_START + 7200, "open_interest": 495_000_000.0},
    # Cycle 4: calm market → no signal
    {"funding_rate": 0.0001, "btc_price": 68100.0,
     "timestamp": FIXED_CLOCK_START + 10800, "open_interest": 500_000_000.0},
    # Cycle 5: extreme positive funding → LONG signal
    {"funding_rate": 0.0012, "btc_price": 69000.0,
     "timestamp": FIXED_CLOCK_START + 14400, "open_interest": 520_000_000.0},
    # Cycle 6: funding drops → assumption met → exit
    {"funding_rate": 0.00008, "btc_price": 69200.0,
     "timestamp": FIXED_CLOCK_START + 18000, "open_interest": 510_000_000.0},
    # Cycle 7-12: repeat for second trading cycle
    {"funding_rate": -0.0008, "btc_price": 68000.0,
     "timestamp": FIXED_CLOCK_START + 21600, "open_interest": 500_000_000.0},
    {"funding_rate": -0.0004, "btc_price": 67800.0,
     "timestamp": FIXED_CLOCK_START + 25200, "open_interest": 490_000_000.0},
    {"funding_rate": -0.00005, "btc_price": 67900.0,
     "timestamp": FIXED_CLOCK_START + 28800, "open_interest": 495_000_000.0},
    {"funding_rate": 0.0001, "btc_price": 68100.0,
     "timestamp": FIXED_CLOCK_START + 32400, "open_interest": 500_000_000.0},
    {"funding_rate": 0.0012, "btc_price": 69000.0,
     "timestamp": FIXED_CLOCK_START + 36000, "open_interest": 520_000_000.0},
    {"funding_rate": 0.00008, "btc_price": 69200.0,
     "timestamp": FIXED_CLOCK_START + 39600, "open_interest": 510_000_000.0},
]


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


# ── The test ────────────────────────────────────────────────────────

DEMO_OUTPUT_PATH = Path("tests/demo_output.txt")


def _run_once() -> tuple[str, dict]:
    """Run the full loop once, return (captured_output, summary)."""
    lines: list[str] = []

    def capture(line: str) -> None:
        lines.append(line)

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        # Reset journal module state
        journal._conn = None

        # Seed with track record so reliability > 0.5 (Lean sizes to 0 at ≤ 0.5)
        journal.init_db(db_path)
        journal.seed_assumptions()
        journal.update_assumption_stats(
            "funding_rate_reverts_within_8h", {"wins": 3, "total": 5}
        )
        journal._conn = None  # reset so run_loop re-inits cleanly

        summary = run_loop(
            observer=DeterministicObserver(SCENARIOS),
            executor=FakeExecutor(initial_equity=10000.0),
            core=VeritasCore(),
            db_path=db_path,
            max_cycles=len(SCENARIOS),
            clock=DeterministicClock(),
            log_fn=capture,
        )

    return "\n".join(lines) + "\n", summary


def test_full_loop_deterministic():
    """The loop completes trades and produces identical output across runs."""
    # Run 1
    output1, summary1 = _run_once()

    # Run 2
    output2, summary2 = _run_once()

    # ── Correctness assertions ──
    assert summary1["trades"] >= 2, (
        f"Expected at least 2 completed trades, got {summary1['trades']}"
    )
    assert summary1["cycles"] == len(SCENARIOS)
    assert summary1["final_stats"] is not None
    assert summary1["final_stats"]["total"] >= 2, (
        "Assumption library should have been updated"
    )

    # ── Determinism assertion ──
    assert output1 == output2, (
        "Two runs produced different output — determinism violated.\n"
        f"DIFF (first 500 chars):\n"
        f"RUN1: {output1[:500]}\n"
        f"RUN2: {output2[:500]}"
    )

    # ── Write demo output ──
    DEMO_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEMO_OUTPUT_PATH.write_text(output1)
    print(f"\n[demo_output.txt written: {len(output1)} bytes, "
          f"{summary1['trades']} trades, "
          f"{summary1['cycles']} cycles]")


def test_no_python_decision_logic():
    """Verify Python shell contains no trade decision logic.

    The grep commands from PRODUCT_BRIEF: if Python has if/else that
    affects Signal, ExitDecision, or PositionSize, the architecture is broken.
    """
    import subprocess

    result = subprocess.run(
        ["grep", "-rnE", r"if.*(Signal|ExitDecision|PositionSize)", "python/"],
        capture_output=True, text=True,
    )
    assert result.stdout.strip() == "", (
        f"Python contains decision logic:\n{result.stdout}"
    )
