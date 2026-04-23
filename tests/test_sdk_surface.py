"""Tests for ``python.sdk`` — the caller-side SDK surface (v0.3 slice 9).

The SDK is meant to be usable by external agents that never run the
Lean kernel locally. These tests enforce that contract:

- Importing ``python.sdk`` does NOT pull in ``python.bridge`` (which
  is the subprocess shim to ``veritas-core``).
- Every expected name is exported.
- A full round-trip — build inputs, sign with the same helpers, call
  ``verify_certificate`` — goes through using only SDK symbols.
"""

from __future__ import annotations

import base64
import importlib
import sys

import pytest


def test_sdk_import_does_not_pull_in_bridge():
    """The SDK must be Lean-binary-free. An external agent installs
    only SDK dependencies and never invokes ``veritas-core``. Pulling
    ``python.bridge`` in transitively would leak that intent."""
    # Flush cached imports that earlier tests may have pulled in.
    for mod in list(sys.modules):
        if mod == "python.bridge" or mod.startswith("python.bridge."):
            del sys.modules[mod]
        if mod == "python.sdk":
            del sys.modules[mod]
    importlib.import_module("python.sdk")
    assert "python.bridge" not in sys.modules, (
        "python.sdk leaked a transitive import of python.bridge, "
        "breaking the Lean-binary-free SDK contract."
    )


def test_sdk_exports_match_declared_all():
    from python import sdk
    for name in sdk.__all__:
        assert hasattr(sdk, name), f"SDK missing declared export {name!r}"
    # Invariant: nothing in __all__ shadows a private helper
    assert all(not n.startswith("_") for n in sdk.__all__)


def test_sdk_exports_required_surface():
    from python import sdk
    required = {
        # Input types
        "TradeProposal", "AccountConstraints", "Portfolio",
        "PortfolioPosition", "CorrelationEntry",
        # Output types
        "Certificate", "Verdict", "Attestation",
        # Verification functions
        "compute_request_digest", "verify_certificate",
        "AttestationError",
    }
    exported = set(sdk.__all__)
    assert required <= exported, (
        f"SDK is missing required names: {sorted(required - exported)}"
    )


def test_sdk_end_to_end_verify_round_trip():
    """Caller-side use case: an agent constructs inputs, receives a
    (sign-for-test) Certificate, and independently verifies it — all
    through the SDK surface, no verifier-side imports."""
    from python import sdk
    # Signing is verifier-side machinery; we import the minimum
    # needed to fabricate an attestation for this test. In production
    # the caller never signs — only verifies.
    from python.attestation import SigningKey, sign_certificate_body

    # 1. Build inputs using SDK types only.
    proposal = sdk.TradeProposal(
        direction="LONG", notional_usd=1500.0,
        funding_rate=0.0012, price=68000.0, timestamp=0,
    )
    constraints = sdk.AccountConstraints(
        equity=10000.0, reliability=0.8, sample_size=20,
    )
    portfolio = sdk.Portfolio()

    # 2. Simulate what Veritas would send back: a signed Certificate.
    key = SigningKey.from_seed(b"\x11" * 32)
    body = {
        "gate1": sdk.Verdict(tag="approve").to_json(),
        "gate2": sdk.Verdict(tag="approve").to_json(),
        "gate3": sdk.Verdict(tag="approve").to_json(),
        "assumptions": [],
        "final_notional_usd": 1500.0,
        "approves": True,
    }
    digest = sdk.compute_request_digest(proposal, constraints, portfolio)
    att = sign_certificate_body(
        body, signing_key=key, build_sha="deadbeef" * 8,
        request_digest=digest,
    )
    cert_json = {**body, "attestation": att.to_json()}

    # 3. Caller-side: decode + verify, using only SDK symbols.
    cert = sdk.Certificate.from_json(cert_json)
    assert cert.approves is True
    sdk.verify_certificate(
        cert.body_json(), cert.attestation,
        expected_public_key=key.public_key_b64,
        expected_request_digest=digest,
    )


def test_sdk_verify_rejects_mismatched_request_digest():
    """Core replay-protection property (slice 4): a digest computed
    from different inputs refuses to verify, even if everything else
    is legitimate."""
    from python import sdk
    from python.attestation import SigningKey, sign_certificate_body

    key = SigningKey.from_seed(b"\x22" * 32)
    body = {
        "gate1": sdk.Verdict(tag="approve").to_json(),
        "gate2": sdk.Verdict(tag="approve").to_json(),
        "gate3": sdk.Verdict(tag="approve").to_json(),
        "assumptions": [],
        "final_notional_usd": 1000.0,
        "approves": True,
    }
    # Attestation was signed for proposal A.
    proposal_a = sdk.TradeProposal(
        direction="LONG", notional_usd=1000.0,
        funding_rate=0.0012, price=68000.0, timestamp=0,
    )
    digest_a = sdk.compute_request_digest(
        proposal_a, sdk.AccountConstraints(
            equity=10000.0, reliability=0.8, sample_size=20),
        sdk.Portfolio(),
    )
    att = sign_certificate_body(
        body, signing_key=key, build_sha="cafebabe" * 8,
        request_digest=digest_a,
    )

    # Attacker tries to replay for proposal B.
    proposal_b = sdk.TradeProposal(
        direction="SHORT", notional_usd=5000.0,
        funding_rate=-0.0008, price=2000.0, timestamp=1,
    )
    digest_b = sdk.compute_request_digest(
        proposal_b, sdk.AccountConstraints(
            equity=10000.0, reliability=0.8, sample_size=20),
        sdk.Portfolio(),
    )
    with pytest.raises(sdk.AttestationError, match="does not match expected"):
        sdk.verify_certificate(
            body, att,
            expected_public_key=key.public_key_b64,
            expected_request_digest=digest_b,
        )


def test_sdk_verify_rejects_tampered_verdict():
    """If an intermediary flips ``approves`` from false to true, the
    signature no longer matches and the caller rejects the response."""
    from python import sdk
    from python.attestation import SigningKey, sign_certificate_body

    key = SigningKey.from_seed(b"\x33" * 32)
    proposal = sdk.TradeProposal(
        direction="LONG", notional_usd=1500.0,
        funding_rate=0.0012, price=68000.0, timestamp=0,
    )
    constraints = sdk.AccountConstraints(
        equity=10000.0, reliability=0.8, sample_size=20,
    )
    portfolio = sdk.Portfolio()
    digest = sdk.compute_request_digest(proposal, constraints, portfolio)

    body = {
        "gate1": sdk.Verdict(tag="reject", reason_codes=("x",)).to_json(),
        "gate2": sdk.Verdict(tag="reject",
                              reason_codes=("upstream_gate_rejected",)).to_json(),
        "gate3": sdk.Verdict(tag="reject",
                              reason_codes=("upstream_gate_rejected",)).to_json(),
        "assumptions": [],
        "final_notional_usd": 0.0,
        "approves": False,
    }
    att = sign_certificate_body(
        body, signing_key=key, build_sha="0" * 64,
        request_digest=digest,
    )

    # Attacker flips approves -> true without touching the signature.
    tampered = {**body, "approves": True, "attestation": att.to_json()}
    cert = sdk.Certificate.from_json(tampered)
    with pytest.raises(sdk.AttestationError, match="does not verify"):
        sdk.verify_certificate(
            cert.body_json(), cert.attestation,
            expected_public_key=key.public_key_b64,
            expected_request_digest=digest,
        )
