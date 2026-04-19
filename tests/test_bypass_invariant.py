"""Invariants that protect Veritas's trust boundary.

These tests assert properties of the Python codebase, not of any
particular trade. They exist so that a future edit that accidentally
introduces gate logic into Python fails CI.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


PY_DIR = Path("python")


def _grep(pattern: str) -> str:
    result = subprocess.run(
        ["grep", "-rnE", pattern, str(PY_DIR)],
        capture_output=True, text=True,
    )
    return result.stdout


def test_no_python_decision_logic():
    """Python must contain no trade-decision branching on Veritas types."""
    output = _grep(r"if.*(Signal|ExitDecision|PositionSize)")
    assert output.strip() == "", (
        "Python has reintroduced decision logic. "
        "Move it to Lean and call it via the bridge.\n" + output
    )


def test_no_python_gate_bypass():
    """No Python file should re-implement a verdict outside the bridge.

    The only acceptable places to assemble Verdict literals are:
      - python/schemas.py (the dataclass defines them)
      - python/verifier.py (deserializes from the kernel)
      - tests/ (pattern-matching in assertions)

    Any other occurrence of `Verdict(tag="approve"` / `"reject"` / `"resize"`
    in python/ means a Python caller is minting verdicts directly instead of
    asking the Lean kernel.
    """
    output = _grep(r"Verdict\(tag=\"(approve|reject|resize)\"")
    offending = []
    for line in output.splitlines():
        path = line.split(":", 1)[0]
        if path.endswith(("python/schemas.py", "python/verifier.py")):
            continue
        offending.append(line)
    assert not offending, (
        "Python is minting Verdicts outside the schema / verifier bridge:\n"
        + "\n".join(offending)
    )


def test_bridge_is_only_lean_entry_point():
    """Only python/bridge.py is allowed to invoke the veritas-core binary.

    Other modules must go through the bridge so every kernel call is
    auditable.
    """
    output = _grep(r"veritas-core")
    offending = []
    for line in output.splitlines():
        path = line.split(":", 1)[0]
        # Allowed: the bridge itself, and docstrings / comments anywhere.
        if path.endswith("python/bridge.py"):
            continue
        # Allow references in documentation strings by filtering the
        # subprocess-call signature specifically.
        if "subprocess.run" in line or "subprocess.Popen" in line:
            offending.append(line)
    assert not offending, (
        "Python is invoking veritas-core outside python/bridge.py:\n"
        + "\n".join(offending)
    )
