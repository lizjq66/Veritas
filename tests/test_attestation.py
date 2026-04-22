"""End-to-end tests for certificate attestation.

Covers schema v1 (slice 3 — provenance binding only) and schema v2
(slice 4 — provenance + request-digest binding). v2 is the current
emitted version; v1 must continue to verify forever."""

from __future__ import annotations

import base64
import hashlib
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
    _canonical_payload_v1,
    canonical_json_bytes,
    compute_build_sha,
    compute_request_digest,
    sign_certificate_body,
    verify_certificate,
)
from python.bridge import BINARY_PATH
from python.schemas import (
    AccountConstraints,
    CorrelationEntry,
    Portfolio,
    PortfolioPosition,
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
    assert k1.sign(b"hello") == k2.sign(b"hello")


def test_signing_key_from_seed_rejects_wrong_length():
    with pytest.raises(ValueError, match="32 bytes"):
        SigningKey.from_seed(b"\x01" * 16)


def test_signing_key_from_env_uses_env_seed(monkeypatch):
    seed = b"\x02" * 32
    monkeypatch.setenv("VERITAS_SIGNING_KEY",
                       base64.b64encode(seed).decode("ascii"))
    assert (SigningKey.from_env().public_key_b64
            == SigningKey.from_seed(seed).public_key_b64)


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


# ── Sign / verify round trip (v2 — current) ───────────────────────

def _body() -> dict:
    return {"gate1": {"verdict": "approve"},
            "gate2": {"verdict": "approve"},
            "gate3": {"verdict": "approve"},
            "assumptions": [],
            "final_notional_usd": 1500.0,
            "approves": True}


_DUMMY_DIGEST = "0" * 64  # valid hex sha256 shape but arbitrary content


def test_sign_v2_round_trip():
    key = SigningKey.from_seed(b"\x03" * 32)
    att = sign_certificate_body(
        _body(), signing_key=key, build_sha="abc",
        request_digest=_DUMMY_DIGEST,
    )
    assert att.schema_version == 2
    assert att.request_digest == _DUMMY_DIGEST
    verify_certificate(_body(), att, expected_request_digest=_DUMMY_DIGEST)


def test_verify_v2_rejects_tampered_body():
    key = SigningKey.from_seed(b"\x04" * 32)
    att = sign_certificate_body(
        _body(), signing_key=key, build_sha="abc",
        request_digest=_DUMMY_DIGEST,
    )
    tampered = {**_body(), "approves": False}
    with pytest.raises(AttestationError, match="does not verify"):
        verify_certificate(tampered, att, expected_request_digest=_DUMMY_DIGEST)


def test_verify_v2_rejects_tampered_request_digest_field():
    key = SigningKey.from_seed(b"\x05" * 32)
    att = sign_certificate_body(
        _body(), signing_key=key, build_sha="abc",
        request_digest=_DUMMY_DIGEST,
    )
    tampered = replace(att, request_digest="f" * 64)
    # The signature signed _DUMMY_DIGEST, not "f"*64; even if the
    # caller's expectation now agrees with the tampered field, the
    # cryptographic verify fails.
    with pytest.raises(AttestationError, match="does not verify"):
        verify_certificate(_body(), tampered,
                           expected_request_digest="f" * 64)


def test_verify_v2_rejects_mismatched_expected_digest():
    key = SigningKey.from_seed(b"\x06" * 32)
    att = sign_certificate_body(
        _body(), signing_key=key, build_sha="abc",
        request_digest=_DUMMY_DIGEST,
    )
    with pytest.raises(AttestationError, match="does not match expected"):
        verify_certificate(_body(), att,
                           expected_request_digest="1" * 64)


def test_verify_v2_rejects_missing_expected_request_digest():
    key = SigningKey.from_seed(b"\x07" * 32)
    att = sign_certificate_body(
        _body(), signing_key=key, build_sha="abc",
        request_digest=_DUMMY_DIGEST,
    )
    with pytest.raises(AttestationError,
                       match="requires expected_request_digest"):
        verify_certificate(_body(), att)


def test_verify_v2_rejects_attestation_missing_request_digest_field():
    # Impossible to produce via sign_certificate_body but could arise
    # from a malformed incoming attestation — we must reject explicitly.
    key = SigningKey.from_seed(b"\x08" * 32)
    att = sign_certificate_body(
        _body(), signing_key=key, build_sha="abc",
        request_digest=_DUMMY_DIGEST,
    )
    broken = replace(att, request_digest=None)
    with pytest.raises(AttestationError, match="missing request_digest"):
        verify_certificate(_body(), broken,
                           expected_request_digest=_DUMMY_DIGEST)


def test_verify_v2_rejects_wrong_expected_public_key():
    key = SigningKey.from_seed(b"\x09" * 32)
    other = SigningKey.from_seed(b"\x0a" * 32)
    att = sign_certificate_body(
        _body(), signing_key=key, build_sha="abc",
        request_digest=_DUMMY_DIGEST,
    )
    with pytest.raises(AttestationError, match="does not match expected key"):
        verify_certificate(_body(), att,
                           expected_public_key=other.public_key_b64,
                           expected_request_digest=_DUMMY_DIGEST)


def test_verify_rejects_unsupported_schema_version():
    att = Attestation(
        schema_version=999,
        veritas_version="x", build_sha="x", public_key="pk",
        signed_at="2026-04-22T18:00:00Z", signature="sig",
    )
    with pytest.raises(AttestationError, match="unsupported schema_version"):
        verify_certificate(_body(), att)


def test_current_schema_version_is_supported():
    assert CURRENT_SCHEMA_VERSION in SUPPORTED_SCHEMA_VERSIONS


def test_current_schema_version_is_v2():
    # Regression guard: slice 4 bumped emission to v2. If this ever
    # drops back to 1 without a schema bump it's a bug.
    assert CURRENT_SCHEMA_VERSION == 2


# ── Schema v1 backward compat ─────────────────────────────────────

def _manually_sign_v1(
    body: dict,
    key: SigningKey,
    build_sha: str = "legacy_v1_build",
    veritas_version: str = "0.3.3",
    signed_at: str = "2026-04-20T00:00:00Z",
) -> Attestation:
    """Simulate an attestation issued by the slice-3 Verifier.

    Goes straight to _canonical_payload_v1 so we can exercise the
    v1 verification path in a post-v2 world. Mirrors what slice-3
    sign_certificate_body used to produce before this slice bumped
    CURRENT_SCHEMA_VERSION to 2."""
    payload = _canonical_payload_v1(
        schema_version=1, veritas_version=veritas_version,
        build_sha=build_sha, public_key=key.public_key_b64,
        signed_at=signed_at, certificate_body=body,
    )
    return Attestation(
        schema_version=1, veritas_version=veritas_version,
        build_sha=build_sha, public_key=key.public_key_b64,
        signed_at=signed_at,
        signature=base64.b64encode(key.sign(payload)).decode("ascii"),
    )


def test_v1_attestation_still_verifies_under_v2_codepath():
    """Slice-3-era certs must remain verifiable indefinitely."""
    key = SigningKey.from_seed(b"\xaa" * 32)
    att = _manually_sign_v1(_body(), key)
    assert att.schema_version == 1
    # No expected_request_digest needed for v1 — the argument is ignored.
    verify_certificate(_body(), att)


def test_v1_verify_ignores_expected_request_digest():
    key = SigningKey.from_seed(b"\xab" * 32)
    att = _manually_sign_v1(_body(), key)
    # Even if the caller passes one (say, out of habit), v1 does not
    # bind to inputs and thus does not consult it.
    verify_certificate(_body(), att, expected_request_digest=_DUMMY_DIGEST)


def test_v1_verify_rejects_tampered_body():
    key = SigningKey.from_seed(b"\xac" * 32)
    att = _manually_sign_v1(_body(), key)
    with pytest.raises(AttestationError, match="does not verify"):
        verify_certificate({**_body(), "approves": False}, att)


# ── JSON wire format ──────────────────────────────────────────────

def test_v2_attestation_json_includes_request_digest():
    key = SigningKey.from_seed(b"\x0b" * 32)
    att = sign_certificate_body(
        _body(), signing_key=key, build_sha="x",
        request_digest=_DUMMY_DIGEST,
    )
    d = att.to_json()
    assert d["schema_version"] == 2
    assert d["request_digest"] == _DUMMY_DIGEST


def test_v1_attestation_json_omits_null_request_digest():
    key = SigningKey.from_seed(b"\x0c" * 32)
    att = _manually_sign_v1(_body(), key)
    d = att.to_json()
    assert "request_digest" not in d
    assert d["schema_version"] == 1


def test_attestation_roundtrip_through_json():
    key = SigningKey.from_seed(b"\x0d" * 32)
    att = sign_certificate_body(
        _body(), signing_key=key, build_sha="x",
        request_digest=_DUMMY_DIGEST,
    )
    assert Attestation.from_json(att.to_json()) == att


# ── compute_request_digest ────────────────────────────────────────

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


def test_compute_request_digest_deterministic():
    d1 = compute_request_digest(_proposal(), _constraints(), Portfolio())
    d2 = compute_request_digest(_proposal(), _constraints(), Portfolio())
    assert d1 == d2
    assert len(d1) == 64  # hex sha256
    int(d1, 16)  # parses as hex


def test_compute_request_digest_sensitive_to_proposal():
    d1 = compute_request_digest(_proposal(), _constraints(), Portfolio())
    other = TradeProposal(
        direction="SHORT", notional_usd=1500.0,
        funding_rate=-0.0008, price=68000.0, timestamp=0,
    )
    d2 = compute_request_digest(other, _constraints(), Portfolio())
    assert d1 != d2


def test_compute_request_digest_sensitive_to_constraints():
    d1 = compute_request_digest(_proposal(), _constraints(), Portfolio())
    d2 = compute_request_digest(
        _proposal(),
        replace(_constraints(), equity=20000.0),
        Portfolio(),
    )
    assert d1 != d2


def test_compute_request_digest_sensitive_to_portfolio():
    d1 = compute_request_digest(_proposal(), _constraints(), Portfolio())
    port = Portfolio(
        positions=(PortfolioPosition(
            direction="LONG", entry_price=68000.0, size=0.01),),
    )
    d2 = compute_request_digest(_proposal(), _constraints(), port)
    assert d1 != d2


def test_compute_request_digest_treats_none_and_empty_portfolio_differently():
    # A caller that passes None should not accidentally collide with
    # one that passes Portfolio() — they go through different code
    # paths on the Verifier side too.
    d_none = compute_request_digest(_proposal(), _constraints(), None)
    d_empty = compute_request_digest(_proposal(), _constraints(), Portfolio())
    assert d_none != d_empty


def test_compute_request_digest_accepts_plain_dicts():
    # Advanced callers (non-Python SDKs) might rebuild the dict shape
    # manually. As long as the dict matches asdict(schema), the digest
    # must match.
    from dataclasses import asdict
    p = _proposal()
    c = _constraints()
    port = Portfolio()
    d_dataclass = compute_request_digest(p, c, port)
    d_dict = compute_request_digest(asdict(p), asdict(c), asdict(port))
    assert d_dataclass == d_dict


# ── Certificate-level e2e through the real Lean kernel ────────────

@pytest.fixture
def verifier(monkeypatch) -> Verifier:
    seed = base64.b64encode(b"\x42" * 32).decode("ascii")
    monkeypatch.setenv("VERITAS_SIGNING_KEY", seed)
    return Verifier()


def test_verifier_returns_v2_attestation_with_request_digest(verifier):
    cert = verifier.verify(_proposal(), _constraints())
    att = cert.attestation
    assert att is not None
    assert att.schema_version == 2
    assert att.public_key == verifier.public_key
    assert att.build_sha == verifier.build_sha
    assert att.request_digest is not None
    assert len(att.request_digest) == 64


def test_caller_can_verify_roundtrip_via_compute_request_digest(verifier):
    p, c = _proposal(), _constraints()
    cert = verifier.verify(p, c)
    digest = compute_request_digest(p, c, Portfolio())
    verify_certificate(
        cert.body_json(), cert.attestation,
        expected_request_digest=digest,
    )


def test_replay_to_different_proposal_fails(verifier):
    """The signature bound to proposal X cannot be reused as proof
    of a different proposal Y."""
    p_x, c = _proposal(), _constraints()
    cert = verifier.verify(p_x, c)
    # Attacker tries to replay cert for an unrelated proposal.
    p_y = TradeProposal(
        direction="SHORT", notional_usd=5000.0,
        funding_rate=-0.0008, price=2000.0, timestamp=1,
    )
    digest_y = compute_request_digest(p_y, c, Portfolio())
    with pytest.raises(AttestationError, match="does not match expected"):
        verify_certificate(
            cert.body_json(), cert.attestation,
            expected_request_digest=digest_y,
        )


def test_certificate_attestation_fails_after_verdict_tamper(verifier):
    p, c = _proposal(), _constraints()
    cert = verifier.verify(p, c)
    tampered = replace(
        cert, gate1=Verdict(tag="reject", reason_codes=("synthetic",)),
    )
    digest = compute_request_digest(p, c, Portfolio())
    with pytest.raises(AttestationError):
        verify_certificate(
            tampered.body_json(), cert.attestation,
            expected_request_digest=digest,
        )


def test_verifier_build_sha_matches_compiled_binary(verifier):
    expected = compute_build_sha(BINARY_PATH)
    cert = verifier.verify(_proposal(), _constraints())
    assert cert.attestation.build_sha == expected == verifier.build_sha


def test_opt_out_of_signing_produces_no_attestation():
    v = Verifier(sign_certificates=False)
    assert v.public_key is None and v.build_sha is None
    cert = v.verify(_proposal(), _constraints())
    assert cert.attestation is None


def test_certificate_json_roundtrip_preserves_attestation(verifier):
    p, c = _proposal(), _constraints()
    cert = verifier.verify(p, c)
    from python.schemas import Certificate
    cert2 = Certificate.from_json(cert.to_json())
    assert cert2.attestation == cert.attestation
    verify_certificate(
        cert2.body_json(), cert2.attestation,
        expected_request_digest=compute_request_digest(p, c, Portfolio()),
    )


# ── HTTP: GET /verify/pubkey and /verify/proposal integration ─────

def test_pubkey_endpoint_returns_current_key(monkeypatch):
    seed = base64.b64encode(b"\x55" * 32).decode("ascii")
    monkeypatch.setenv("VERITAS_SIGNING_KEY", seed)
    verify_route._verifier = None

    from python.api.server import app
    client = TestClient(app)
    r = client.get("/verify/pubkey")
    assert r.status_code == 200
    d = r.json()
    assert d["algorithm"] == "ed25519"
    assert d["schema_version"] == CURRENT_SCHEMA_VERSION == 2
    assert len(base64.b64decode(d["public_key"])) == 32
    assert len(d["build_sha"]) == 64


def test_http_verify_proposal_returns_v2_attestation(monkeypatch):
    seed = base64.b64encode(b"\x66" * 32).decode("ascii")
    monkeypatch.setenv("VERITAS_SIGNING_KEY", seed)
    verify_route._verifier = None

    from python.api.server import app
    client = TestClient(app)
    proposal_body = {"direction": "LONG", "notional_usd": 1500.0,
                     "funding_rate": 0.0012, "price": 68000.0}
    constraints_body = {"equity": 10000.0, "reliability": 0.8,
                        "sample_size": 20}
    r = client.post("/verify/proposal", json={
        "proposal": proposal_body,
        "constraints": constraints_body,
        "portfolio": None,
    })
    assert r.status_code == 200
    d = r.json()
    att = d.get("attestation")
    assert att is not None
    assert att["schema_version"] == 2
    assert "request_digest" in att

    # Caller reconstructs inputs and verifies end-to-end.
    from python.api.routes.verify import (
        _to_constraints, _to_portfolio, _to_proposal, ProposalIn,
        ConstraintsIn,
    )
    p = _to_proposal(ProposalIn(**proposal_body))
    c = _to_constraints(ConstraintsIn(**constraints_body))
    digest = compute_request_digest(p, c, Portfolio())
    body = {k: v for k, v in d.items() if k != "attestation"}
    verify_certificate(
        body, Attestation.from_json(att),
        expected_request_digest=digest,
    )
