"""End-to-end tests for certificate attestation (v0.3 slice 3).

Verifies: Ed25519 key management (env + ephemeral), canonical-JSON
sign/verify round-trips, tamper detection, wrong-key rejection,
unsupported-schema rejection, JSON wire format (slice-3 must not
include ``request_digest``), and the full pipeline through the real
Lean kernel — Verifier → signed Certificate → caller-side verify."""

from __future__ import annotations

import base64
import logging
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from python.api.routes import verify as verify_route
from python.attestation import (
    CURRENT_SCHEMA_VERSION,
    SUPPORTED_SCHEMA_VERSIONS,
    Attestation,
    AttestationError,
    SigningKey,
    compute_build_sha,
    sign_certificate_body,
    verify_certificate,
)
from python.bridge import BINARY_PATH
from python.schemas import (
    AccountConstraints,
    Portfolio,
    TradeProposal,
    Verdict,
)
from python.verifier import Verifier


# ── SigningKey: env and ephemeral ─────────────────────────────────

def test_signing_key_from_seed_deterministic():
    seed = b"\x01" * 32
    k1 = SigningKey.from_seed(seed)
    k2 = SigningKey.from_seed(seed)
    assert k1.public_key_b64 == k2.public_key_b64
    # Same seed, same message → same signature (Ed25519 is deterministic).
    assert k1.sign(b"hello") == k2.sign(b"hello")


def test_signing_key_from_seed_rejects_wrong_length():
    with pytest.raises(ValueError, match="32 bytes"):
        SigningKey.from_seed(b"\x01" * 16)


def test_signing_key_from_env_uses_env_seed(monkeypatch):
    seed = b"\x02" * 32
    monkeypatch.setenv("VERITAS_SIGNING_KEY",
                       base64.b64encode(seed).decode("ascii"))
    k1 = SigningKey.from_env()
    k2 = SigningKey.from_seed(seed)
    assert k1.public_key_b64 == k2.public_key_b64


def test_signing_key_from_env_rejects_bad_base64(monkeypatch):
    monkeypatch.setenv("VERITAS_SIGNING_KEY", "not-base64!!!")
    with pytest.raises(ValueError, match="not valid base64"):
        SigningKey.from_env()


def test_signing_key_from_env_ephemeral_when_unset(monkeypatch, caplog):
    monkeypatch.delenv("VERITAS_SIGNING_KEY", raising=False)
    caplog.set_level(logging.WARNING, logger="veritas.attestation")
    k = SigningKey.from_env()
    assert len(base64.b64decode(k.public_key_b64)) == 32
    assert any("ephemeral" in r.message.lower() for r in caplog.records)


# ── sign / verify: round trip and failure modes ───────────────────

def _body() -> dict:
    return {"gate1": {"verdict": "approve"},
            "gate2": {"verdict": "approve"},
            "gate3": {"verdict": "approve"},
            "assumptions": [],
            "final_notional_usd": 1500.0,
            "approves": True}


def test_sign_then_verify_roundtrip():
    key = SigningKey.from_seed(b"\x03" * 32)
    att = sign_certificate_body(_body(), signing_key=key, build_sha="abc123")
    assert att.schema_version == CURRENT_SCHEMA_VERSION
    assert att.build_sha == "abc123"
    assert att.public_key == key.public_key_b64
    assert att.signature  # non-empty
    verify_certificate(_body(), att)  # must not raise


def test_verify_rejects_tampered_body():
    key = SigningKey.from_seed(b"\x04" * 32)
    att = sign_certificate_body(_body(), signing_key=key, build_sha="abc")
    tampered = {**_body(), "approves": False}
    with pytest.raises(AttestationError, match="does not verify"):
        verify_certificate(tampered, att)


def test_verify_rejects_tampered_attestation_field():
    key = SigningKey.from_seed(b"\x0a" * 32)
    att = sign_certificate_body(_body(), signing_key=key, build_sha="abc")
    # Swap build_sha post-sign: signed payload now disagrees with what
    # the verifier reconstructs from the tampered attestation → reject.
    tampered = replace(att, build_sha="different_build")
    with pytest.raises(AttestationError, match="does not verify"):
        verify_certificate(_body(), tampered)


def test_verify_rejects_wrong_expected_public_key():
    key = SigningKey.from_seed(b"\x05" * 32)
    other = SigningKey.from_seed(b"\x06" * 32)
    att = sign_certificate_body(_body(), signing_key=key, build_sha="abc")
    with pytest.raises(AttestationError, match="does not match expected key"):
        verify_certificate(_body(), att,
                           expected_public_key=other.public_key_b64)


def test_verify_accepts_matching_expected_public_key():
    key = SigningKey.from_seed(b"\x07" * 32)
    att = sign_certificate_body(_body(), signing_key=key, build_sha="abc")
    verify_certificate(_body(), att, expected_public_key=key.public_key_b64)


def test_verify_rejects_unsupported_schema_version():
    att = Attestation(
        schema_version=999,
        veritas_version="0.3.3",
        build_sha="abc", public_key="pk",
        signed_at="2026-04-22T18:00:00Z",
        signature="sig",
    )
    with pytest.raises(AttestationError, match="unsupported schema_version"):
        verify_certificate(_body(), att)


def test_current_schema_version_is_supported():
    # Contract: whatever CURRENT_SCHEMA_VERSION we emit must be in the
    # supported set (so we can verify our own output).
    assert CURRENT_SCHEMA_VERSION in SUPPORTED_SCHEMA_VERSIONS


# ── Forward-compat: slice-3 JSON must NOT carry request_digest ─────

def test_attestation_json_omits_null_request_digest():
    key = SigningKey.from_seed(b"\x08" * 32)
    att = sign_certificate_body(_body(), signing_key=key, build_sha="x")
    d = att.to_json()
    assert "request_digest" not in d
    assert d["schema_version"] == 1


def test_attestation_from_json_tolerates_future_request_digest():
    # Forward-compat: a future schema v2 cert might include request_digest.
    # from_json for v1 must at least not crash on its presence.
    key = SigningKey.from_seed(b"\x09" * 32)
    att = sign_certificate_body(_body(), signing_key=key, build_sha="x")
    d = att.to_json()
    d["request_digest"] = "0" * 64  # simulate future field
    att2 = Attestation.from_json(d)
    assert att2.request_digest == "0" * 64


def test_attestation_roundtrip_through_json():
    key = SigningKey.from_seed(b"\x0b" * 32)
    att = sign_certificate_body(_body(), signing_key=key, build_sha="x")
    att2 = Attestation.from_json(att.to_json())
    assert att2 == att


# ── Certificate-level e2e through the real Lean kernel ────────────

@pytest.fixture
def verifier(monkeypatch) -> Verifier:
    """Deterministic signing key so test assertions about public_key
    are stable across runs."""
    seed = base64.b64encode(b"\x42" * 32).decode("ascii")
    monkeypatch.setenv("VERITAS_SIGNING_KEY", seed)
    return Verifier()


def _proposal() -> TradeProposal:
    return TradeProposal(
        direction="LONG", notional_usd=1500.0,
        funding_rate=0.0012, price=68000.0, timestamp=0,
    )


def _constraints() -> AccountConstraints:
    return AccountConstraints(
        equity=10000.0, reliability=0.8, sample_size=20,
        max_leverage=1.0, max_position_fraction=0.25, stop_loss_pct=5.0,
    )


def test_verifier_returns_certificate_with_attestation(verifier):
    cert = verifier.verify(_proposal(), _constraints())
    assert cert.attestation is not None
    assert cert.attestation.schema_version == CURRENT_SCHEMA_VERSION
    assert cert.attestation.public_key == verifier.public_key
    assert cert.attestation.build_sha == verifier.build_sha


def test_certificate_attestation_verifies(verifier):
    cert = verifier.verify(_proposal(), _constraints())
    verify_certificate(cert.body_json(), cert.attestation)


def test_certificate_attestation_fails_after_verdict_tamper(verifier):
    cert = verifier.verify(_proposal(), _constraints())
    tampered = replace(
        cert, gate1=Verdict(tag="reject", reason_codes=("synthetic",)),
    )
    with pytest.raises(AttestationError):
        verify_certificate(tampered.body_json(), cert.attestation)


def test_verifier_build_sha_matches_compiled_binary(verifier):
    # Sanity: what Verifier attests in signatures is what you'd get
    # by hashing the binary on disk.
    expected = compute_build_sha(BINARY_PATH)
    cert = verifier.verify(_proposal(), _constraints())
    assert cert.attestation.build_sha == expected
    assert verifier.build_sha == expected


def test_opt_out_of_signing_produces_no_attestation():
    v = Verifier(sign_certificates=False)
    assert v.public_key is None
    assert v.build_sha is None
    cert = v.verify(_proposal(), _constraints())
    assert cert.attestation is None


def test_certificate_json_roundtrip_preserves_attestation(verifier):
    cert = verifier.verify(_proposal(), _constraints())
    from python.schemas import Certificate
    cert2 = Certificate.from_json(cert.to_json())
    assert cert2.attestation == cert.attestation
    # And the reconstructed cert still verifies.
    verify_certificate(cert2.body_json(), cert2.attestation)


# ── HTTP: GET /verify/pubkey ──────────────────────────────────────

def test_pubkey_endpoint_returns_current_key(monkeypatch):
    seed = base64.b64encode(b"\x55" * 32).decode("ascii")
    monkeypatch.setenv("VERITAS_SIGNING_KEY", seed)
    # Force a fresh Verifier so it picks up the patched env.
    verify_route._verifier = None

    from python.api.server import app
    client = TestClient(app)
    r = client.get("/verify/pubkey")
    assert r.status_code == 200
    d = r.json()
    assert d["algorithm"] == "ed25519"
    assert d["schema_version"] == CURRENT_SCHEMA_VERSION
    assert len(base64.b64decode(d["public_key"])) == 32
    assert len(d["build_sha"]) == 64  # sha256 hex
    # And the key it advertises matches what signs real certs.
    r2 = client.post("/verify/proposal", json={
        "proposal": {"direction": "LONG", "notional_usd": 1500.0,
                     "funding_rate": 0.0012, "price": 68000.0},
        "constraints": {"equity": 10000.0, "reliability": 0.8,
                        "sample_size": 20},
        "portfolio": None,
    })
    assert r2.status_code == 200
    assert r2.json()["attestation"]["public_key"] == d["public_key"]
    assert r2.json()["attestation"]["build_sha"] == d["build_sha"]


def test_verify_proposal_response_includes_attestation(monkeypatch):
    seed = base64.b64encode(b"\x66" * 32).decode("ascii")
    monkeypatch.setenv("VERITAS_SIGNING_KEY", seed)
    verify_route._verifier = None

    from python.api.server import app
    client = TestClient(app)
    r = client.post("/verify/proposal", json={
        "proposal": {"direction": "LONG", "notional_usd": 1500.0,
                     "funding_rate": 0.0012, "price": 68000.0},
        "constraints": {"equity": 10000.0, "reliability": 0.8,
                        "sample_size": 20},
        "portfolio": None,
    })
    assert r.status_code == 200
    att = r.json().get("attestation")
    assert att is not None
    assert att["schema_version"] == CURRENT_SCHEMA_VERSION
    assert "signature" in att
    # Caller can verify end-to-end against the HTTP response bytes.
    body = {k: v for k, v in r.json().items() if k != "attestation"}
    verify_certificate(body, Attestation.from_json(att))
