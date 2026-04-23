"""Tests for v0.3 Slice 5 — theorem registry SHA pinning.

Ensures: the registry hash is deterministic; it changes when content
changes (regression guard against silent staleness); the pubkey and
/verify/theorems endpoints expose the same value; and the registry
matches the set of theorems actually declared in Lean source (so a
new Lean theorem shipped without a registry entry is a build-breaker,
not a silent trust-surface downgrade)."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from python.api import theorem_registry as reg
from python.api.server import app

client = TestClient(app)


def test_compute_theorem_registry_sha_deterministic():
    a = reg.compute_theorem_registry_sha()
    b = reg.compute_theorem_registry_sha()
    assert a == b
    assert len(a) == 64
    int(a, 16)  # parses as hex


def test_theorem_registry_canonical_bytes_stable_across_key_order():
    # Build a shuffled copy of the registry; canonical bytes must be
    # identical (the whole point of sort_keys).
    canon = reg.theorem_registry_canonical_bytes()
    shuffled = dict(reversed(list(reg.THEOREMS.items())))
    shuffled_canon = json.dumps(
        shuffled, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    assert canon == shuffled_canon


def test_registry_sha_changes_when_content_changes(monkeypatch):
    original = reg.compute_theorem_registry_sha()
    patched = {**reg.THEOREMS, "__test_sentinel__": {
        "gate": 99, "file": "x.lean", "status": "proven",
        "statement_natural_language": "sentinel",
        "axioms_used": [],
    }}
    monkeypatch.setattr(reg, "THEOREMS", patched)
    changed = reg.compute_theorem_registry_sha()
    assert changed != original


def test_pubkey_endpoint_includes_theorem_registry_sha(monkeypatch):
    import base64
    from python.api.routes import verify as verify_route

    monkeypatch.setenv("VERITAS_SIGNING_KEY",
                       base64.b64encode(b"\x31" * 32).decode("ascii"))
    verify_route._verifier = None  # force Verifier rebuild

    r = client.get("/verify/pubkey")
    assert r.status_code == 200
    d = r.json()
    assert d["theorem_registry_sha"] == reg.compute_theorem_registry_sha()


def test_verify_theorems_endpoint_returns_full_registry():
    r = client.get("/verify/theorems")
    assert r.status_code == 200
    d = r.json()
    assert d["theorem_registry_sha"] == reg.compute_theorem_registry_sha()
    assert d["count"] == len(reg.THEOREMS)
    assert d["count"] == len(_lean_theorem_names())  # registry ↔ Lean parity
    assert set(d["theorems"].keys()) == set(reg.THEOREMS.keys())


def test_verify_theorems_and_pubkey_agree_on_sha(monkeypatch):
    import base64
    from python.api.routes import verify as verify_route

    monkeypatch.setenv("VERITAS_SIGNING_KEY",
                       base64.b64encode(b"\x32" * 32).decode("ascii"))
    verify_route._verifier = None

    pub = client.get("/verify/pubkey").json()
    thms = client.get("/verify/theorems").json()
    assert pub["theorem_registry_sha"] == thms["theorem_registry_sha"]


# ── Registry ↔ Lean alignment ─────────────────────────────────────

_LEAN_DIRS = ("Gates", "Strategy", "Finance", "Learning")
_THEOREM_RE = re.compile(r"^theorem\s+(\w+)", re.MULTILINE)


def _lean_theorem_names() -> set[str]:
    """Collect every `theorem Foo` declared under the tracked dirs."""
    repo_root = Path(__file__).resolve().parents[1]
    names: set[str] = set()
    for d in _LEAN_DIRS:
        base = repo_root / "Veritas" / d
        if not base.exists():
            continue
        for path in base.rglob("*.lean"):
            src = path.read_text()
            names.update(_THEOREM_RE.findall(src))
    return names


def test_registry_covers_every_lean_theorem():
    """Any theorem declared in Veritas/{Gates,Strategy,Finance,Learning}
    must appear in the registry. This guards against shipping a new
    theorem and forgetting to surface it on the trust interface —
    a silent trust-downgrade regression we hit before Slice 5."""
    lean = _lean_theorem_names()
    registry = set(reg.THEOREMS.keys())
    missing_from_registry = lean - registry
    assert not missing_from_registry, (
        f"Lean declares theorems that the registry does not list: "
        f"{sorted(missing_from_registry)}. Add entries to "
        f"python/api/theorem_registry.py."
    )


def test_registry_theorems_all_exist_in_lean():
    """Inverse check: the registry cannot claim theorems that don't
    exist in Lean. Prevents over-claiming the trust surface."""
    lean = _lean_theorem_names()
    missing_from_lean = set(reg.THEOREMS.keys()) - lean
    assert not missing_from_lean, (
        f"Registry lists theorems absent from Lean sources: "
        f"{sorted(missing_from_lean)}."
    )


# ── Entry shape ───────────────────────────────────────────────────

def test_every_registry_entry_has_required_fields():
    required = {"gate", "file", "status", "statement_natural_language",
                "axioms_used"}
    for name, entry in reg.THEOREMS.items():
        missing = required - set(entry.keys())
        assert not missing, f"{name!r} missing fields: {missing}"
        assert entry["status"] in {"proven", "sorry", "axiom"}
        assert isinstance(entry["axioms_used"], list)


def test_every_registered_file_exists():
    repo_root = Path(__file__).resolve().parents[1]
    for name, entry in reg.THEOREMS.items():
        path = repo_root / entry["file"]
        assert path.exists(), (
            f"{name!r} points at {entry['file']} which does not exist"
        )


def test_theorem_registry_sha_matches_manual_computation():
    expected = hashlib.sha256(
        reg.theorem_registry_canonical_bytes()
    ).hexdigest()
    assert reg.compute_theorem_registry_sha() == expected
