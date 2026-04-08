"""Subprocess + JSON bridge to the Lean veritas-core binary.

This is the trust boundary. Python sends data in, Lean decides, Python
reads the decision out. Python never interprets or overrides the decision.
"""

import json
import subprocess
from pathlib import Path

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

    def decide(self, snapshot: dict) -> dict | None:
        """Step 2: Ask Lean core whether to trade."""
        args = [
            str(snapshot["funding_rate"]),
            str(snapshot["btc_price"]),
            str(snapshot["timestamp"]),
        ]
        if "open_interest" in snapshot:
            args.append(str(snapshot["open_interest"]))
        return self._call("decide", args)

    def extract(self, signal: dict) -> list[dict]:
        """Step 3: Ask Lean core to declare assumptions for a signal."""
        result = self._call("extract", [
            signal["direction"],
            str(signal["funding_rate"]),
            str(signal["price"]),
        ])
        return result if result else []

    def size(self, equity: float, reliability: float) -> dict:
        """Step 5: Ask Lean core for position size."""
        return self._call("size", [str(equity), str(reliability)])

    def monitor(self, snapshot: dict, position: dict) -> dict:
        """Step 7: Ask Lean core whether to exit."""
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
        """Step 8: Ask Lean core to compute updated reliability."""
        return self._call("update-reliability", [
            str(stats["wins"]),
            str(stats["total"]),
            exit_reason,
        ])
