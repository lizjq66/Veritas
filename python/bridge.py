from __future__ import annotations

"""Subprocess + JSON bridge to the Lean veritas-core binary.

This is the trust boundary. Python sends data in, Lean decides, Python
reads the decision out. Python never interprets or overrides the decision.

Two surfaces live here:

    1. Gate methods (verify_signal / check_constraints / check_portfolio /
       emit_certificate / classify_exit) — the verifier product surface.
       These are what `python.verifier.Verifier` drives.

    2. Primitive methods (decide / extract / size / monitor /
       update_reliability / build_context / judge_signal /
       execution_quality) — the building blocks the gates are made of.
       These exist because the bundled example runner still calls them,
       and because adapters sometimes want a single primitive without
       the full gate envelope.

Callers building new features should prefer the gate methods.
"""

import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from python.schemas import (
        AccountConstraints,
        Portfolio,
        TradeProposal,
    )

BINARY_PATH = Path(".lake/build/bin/veritas-core")


class VeritasCore:
    """Bridge to the compiled Lean core."""

    def __init__(self, binary_path: Path = BINARY_PATH) -> None:
        self.binary = str(binary_path)

    def _call(self, command: str, args: list[str]) -> dict | list | None:
        """Run veritas-core with command + args, parse JSON stdout."""
        result = subprocess.run(
            [self.binary, command, *args],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"veritas-core {command} failed (rc={result.returncode}): "
                f"{result.stderr.strip()}"
            )
        stdout = result.stdout.strip()
        if stdout == "null":
            return None
        return json.loads(stdout)

    # ── Gate surface ───────────────────────────────────────────────

    def verify_signal(self, proposal: "TradeProposal") -> dict:
        """Gate 1: signal consistency (multi-policy, v0.2+)."""
        return self._call("verify-signal", [
            proposal.direction,
            str(proposal.funding_rate),
            str(proposal.price),
            str(proposal.timestamp),
            str(proposal.open_interest),
            str(proposal.notional_usd),
            str(proposal.spot_price),
        ])

    def check_constraints(
        self, proposal: "TradeProposal", constraints: "AccountConstraints"
    ) -> dict:
        """Gate 2: strategy-constraint compatibility."""
        return self._call("check-constraints", [
            proposal.direction,
            str(proposal.notional_usd),
            str(constraints.equity),
            str(constraints.reliability),
            str(constraints.sample_size),
            str(constraints.max_leverage),
            str(constraints.max_position_fraction),
            str(constraints.stop_loss_pct),
        ])

    def check_portfolio(
        self,
        proposal: "TradeProposal",
        portfolio: "Portfolio",
        equity: float,
    ) -> dict:
        """Gate 3: portfolio interference (v0.2 — correlation-aware)."""
        base = [
            proposal.direction,
            str(proposal.notional_usd),
            str(equity),
            str(portfolio.max_gross_exposure_fraction),
            proposal.asset,
        ]
        if not portfolio.positions:
            args = base + ["none"]
        else:
            pos = portfolio.positions[0]
            args = base + [
                "one", pos.direction, str(pos.entry_price), str(pos.size),
                pos.asset,
            ]
        args = args + [str(len(portfolio.correlations))]
        for c in portfolio.correlations:
            args += [c.asset_a, c.asset_b, str(c.coefficient)]
        return self._call("check-portfolio-ex", args)

    def emit_certificate(
        self,
        proposal: "TradeProposal",
        constraints: "AccountConstraints",
        portfolio: "Portfolio",
    ) -> dict:
        """Run all three gates and return the combined certificate."""
        base = [
            proposal.direction,
            str(proposal.notional_usd),
            str(proposal.funding_rate),
            str(proposal.price),
            str(proposal.timestamp),
            str(proposal.open_interest),
            str(proposal.spot_price),
            str(constraints.equity),
            str(constraints.reliability),
            str(constraints.sample_size),
            str(constraints.max_leverage),
            str(constraints.max_position_fraction),
            str(constraints.stop_loss_pct),
            str(portfolio.max_gross_exposure_fraction),
            proposal.asset,
        ]
        if not portfolio.positions:
            args = base + ["none"]
        else:
            pos = portfolio.positions[0]
            args = base + [
                "one", pos.direction, str(pos.entry_price), str(pos.size),
                pos.asset,
            ]
        args = args + [str(len(portfolio.correlations))]
        for c in portfolio.correlations:
            args += [c.asset_a, c.asset_b, str(c.coefficient)]
        return self._call("emit-certificate-ex", args)

    def classify_exit(self, snapshot: dict, position: dict) -> dict:
        """Classify whether an open position should exit, and under which
        reason (assumption_met / assumption_broke / stop_loss).

        Semantic rename of the `monitor` primitive under gate vocabulary.
        """
        return self.monitor(snapshot, position)

    # ── Primitive surface (adapters and the bundled example runner) ──

    def decide(self, snapshot: dict) -> dict | None:
        """Policy decider: would Veritas's funding-reversion policy
        emit a signal in this context?"""
        args = [
            str(snapshot["funding_rate"]),
            str(snapshot["btc_price"]),
            str(snapshot["timestamp"]),
        ]
        if "open_interest" in snapshot:
            args.append(str(snapshot["open_interest"]))
        return self._call("decide", args)

    def extract(self, signal: dict) -> list[dict]:
        """Declare the assumptions attached to a signal."""
        result = self._call("extract", [
            signal["direction"],
            str(signal["funding_rate"]),
            str(signal["price"]),
        ])
        return result if result else []

    # ── v0.2 Slice 1 — BasisReversion primitives ────────────────
    # Gate 1 does not yet dispatch to BasisReversion (that is Slice 2);
    # for now these are standalone entry points so the strategy can be
    # exercised and tested in isolation.

    def decide_basis(self, perp_price: float, spot_price: float,
                     timestamp: int = 0) -> dict | None:
        """BasisReversion decider. Returns a signal dict or None."""
        return self._call("decide-basis", [
            str(perp_price), str(spot_price), str(timestamp),
        ])

    def extract_basis(self, signal: dict) -> list[dict]:
        """BasisReversion assumptions for a given signal."""
        result = self._call("extract-basis", [
            signal["direction"], str(signal["price"]),
        ])
        return result if result else []

    def size(self, equity: float, reliability: float, sample_size: int) -> dict:
        """Reliability-adjusted position size (the Gate 2 ceiling)."""
        return self._call("size", [str(equity), str(reliability), str(sample_size)])

    def monitor(self, snapshot: dict, position: dict) -> dict:
        """Classify an open position's exit state."""
        return self._call("monitor", [
            str(snapshot["funding_rate"]),
            str(snapshot["btc_price"]),
            str(snapshot["timestamp"]),
            str(snapshot.get("open_interest", 0)),
            position["direction"],
            str(position["entry_price"]),
            str(position["size"]),
            str(position["leverage"]),
            str(position["stop_loss_pct"]),
            str(position["entry_timestamp"]),
            position["assumption_name"],
        ])

    def update_reliability(self, stats: dict, exit_reason: str) -> dict:
        """Apply the reliability update rule in Lean."""
        return self._call("update-reliability", [
            str(stats["wins"]),
            str(stats["total"]),
            exit_reason,
        ])

    def aggregate_reliability(
        self, stats_list: "list[dict] | tuple[dict, ...]"
    ) -> dict:
        """v0.2 Slice 4 — combine a list of ``{wins, total}`` records
        into the conservative ``(reliability, sample_size)`` pair
        Gate 2 consumes (min across the inputs)."""
        args = [str(len(stats_list))]
        for s in stats_list:
            args += [str(int(s["wins"])), str(int(s["total"]))]
        return self._call("aggregate-reliability", args)

    def build_context(self, snapshot: dict) -> dict:
        """Enrich a raw snapshot with regime / price-change fields."""
        return self._call("build-context", [
            str(snapshot.get("funding_rate", 0)),
            str(snapshot.get("btc_price", 0)),
            str(snapshot.get("open_interest", 0)),
            str(snapshot.get("volume_24h", 0)),
            str(snapshot.get("premium", 0)),
            str(snapshot.get("spread_bps", 0)),
            str(snapshot.get("prev_day_price", snapshot.get("btc_price", 0))),
        ])

    def judge_signal(self, exit_reason: str) -> bool:
        """Given an exit reason, was the original signal direction correct?"""
        result = self._call("judge-signal", [exit_reason])
        return result["signal_correct"] == "true"

    def execution_quality(self, mark_price: float, fill_price: float,
                          exit_price: float, expected_pnl: float,
                          realized_pnl: float) -> dict:
        """Decompose execution quality into slippage / impact / realized vs expected."""
        return self._call("execution-quality", [
            str(mark_price), str(fill_price), str(exit_price),
            str(expected_pnl), str(realized_pnl),
        ])
