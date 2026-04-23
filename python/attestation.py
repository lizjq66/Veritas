"""Certificate attestation — provenance signing for Veritas verdicts.

Veritas's Lean kernel decides; the Python layer attests. Each certificate
returned by the verifier carries an ``Attestation`` that binds the
verdict to (a) a specific ``veritas-core`` binary (by sha256),
(b) a specific signer (by Ed25519 public key), and (c) a timestamp.
The signature covers a canonical representation of the certificate body
plus the other attestation fields, so a caller can independently verify
that this certificate really came from the Veritas build it claims to.

## Trust boundary (v0.3 slice 3)

Python is still NOT trusted to make decisions — ``test_bypass_invariant.py``
continues to enforce that the Lean verdict is the only verdict. Python
IS trusted as a *provenance* anchor: the Ed25519 signing key lives in
the Python process, and the signature asserts "this verdict was
produced by the Lean binary whose sha256 is ``build_sha``". A malicious
Python operator could in principle sign a verdict different from what
Lean returned; defeating that attack requires moving the signer into
Lean (or separating it into an audited side-car), which is an explicit
future direction, not this slice.

## Forward-compatibility contract

The attestation schema is versioned via ``schema_version: int``. Each
version fixes a canonical signed-payload shape:

    v1 (slice 3):
        signed_payload = {
            schema_version, veritas_version, build_sha, public_key,
            signed_at, certificate_body
        }

    v2 (slice 4, current):
        signed_payload = {
            schema_version, veritas_version, build_sha, public_key,
            signed_at, certificate_body, request_digest
        }
        where request_digest = hex sha256 of canonical JSON of
        {proposal, constraints, portfolio} as submitted. This binds
        the signature to specific inputs and defeats replay of a
        valid certificate against a different proposal.

Each version's ``_canonical_payload_vN`` and verification branch are
FROZEN for their lifetime — old certificates must remain verifiable
by newer Verifier versions. ``CURRENT_SCHEMA_VERSION`` is what new
signings emit; ``SUPPORTED_SCHEMA_VERSIONS`` is what verification will
accept. The two diverge for exactly one reason: to carry v1 cert
compatibility forward after we stop emitting them.

## Canonicalization

Signed bytes are:

    json.dumps(payload, sort_keys=True, separators=(",", ":"),
               ensure_ascii=False).encode("utf-8")

This is stable within CPython's JSON conventions. Cross-language
verification (e.g. a JS/Go caller) must reproduce Python's JSON
float formatting to get byte-identical signed input; this is the
known limitation flagged for a later slice to migrate to RFC 8785 JCS.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

log = logging.getLogger("veritas.attestation")

# Schema versions supported by this build. Must list every version for
# which this module can run a valid verification path. Append-only.
SUPPORTED_SCHEMA_VERSIONS: tuple[int, ...] = (1, 2)

# The schema version this build EMITS when signing. Callers verifying
# older certs go through whichever _canonical_payload_vN matches.
CURRENT_SCHEMA_VERSION: int = 2

# Semver of the Veritas release. Independent of schema_version.
VERITAS_VERSION: str = "0.4.0"


# ── Canonical JSON ──────────────────────────────────────────────

def canonical_json_bytes(obj: Any) -> bytes:
    """Canonical JSON form used for signing and verification."""
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


# ── Build SHA ───────────────────────────────────────────────────

def compute_build_sha(binary_path: Path | str) -> str:
    """SHA-256 of the ``veritas-core`` binary. Uniquely identifies the
    compiled Lean kernel that is producing verdicts for this process."""
    h = hashlib.sha256()
    with open(binary_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ── Request digest (schema v2) ──────────────────────────────────

def _normalize_input(x: Any) -> Any:
    """Normalize a dataclass/None/dict into a plain JSON-able shape.

    Used to build the request digest so that callers passing either
    schema dataclasses (TradeProposal, AccountConstraints, Portfolio)
    or raw dicts get the same bytes."""
    if x is None:
        return None
    if is_dataclass(x):
        return asdict(x)
    return x


def compute_request_digest(
    proposal: Any,
    constraints: Any,
    portfolio: Any | None = None,
) -> str:
    """Return hex sha256 of the canonical JSON of the request tuple
    ``{proposal, constraints, portfolio}``.

    This is what a schema v2 Attestation binds to. A caller verifies
    a returned certificate by recomputing this digest from its own
    copy of the submitted inputs and passing it as
    ``expected_request_digest`` to :func:`verify_certificate`.

    Inputs may be either the Veritas schema dataclasses or already-
    normalized dicts; both produce the same digest as long as the
    fields match."""
    data = {
        "proposal": _normalize_input(proposal),
        "constraints": _normalize_input(constraints),
        "portfolio": _normalize_input(portfolio),
    }
    return hashlib.sha256(canonical_json_bytes(data)).hexdigest()


# ── Signing key ─────────────────────────────────────────────────

@dataclass(frozen=True)
class SigningKey:
    """Ed25519 private+public key pair held by the Verifier process."""

    _private: Ed25519PrivateKey
    _public_b64: str

    @property
    def public_key_b64(self) -> str:
        return self._public_b64

    def sign(self, message: bytes) -> bytes:
        return self._private.sign(message)

    @classmethod
    def from_seed(cls, seed: bytes) -> "SigningKey":
        if len(seed) != 32:
            raise ValueError(
                f"Ed25519 seed must be 32 bytes, got {len(seed)}"
            )
        priv = Ed25519PrivateKey.from_private_bytes(seed)
        pub_raw = priv.public_key().public_bytes(
            Encoding.Raw, PublicFormat.Raw
        )
        return cls(
            _private=priv,
            _public_b64=base64.b64encode(pub_raw).decode("ascii"),
        )

    @classmethod
    def from_env(cls, env_var: str = "VERITAS_SIGNING_KEY") -> "SigningKey":
        """Load signing key from env (base64-encoded 32-byte seed).

        If the env var is unset, generates an EPHEMERAL key for this
        process and logs a conspicuous warning. Production deployments
        MUST set the env var to a persistent seed so signatures remain
        verifiable across process restarts and across multiple
        Verifier instances."""
        raw = os.environ.get(env_var)
        if raw:
            try:
                seed = base64.b64decode(raw, validate=True)
            except Exception as e:
                raise ValueError(
                    f"{env_var} is not valid base64: {e}"
                ) from e
            return cls.from_seed(seed)
        log.warning(
            "%s not set — generating an EPHEMERAL Ed25519 key. "
            "Signatures produced by this process will not verify "
            "after restart. Set %s=<base64 32-byte seed> in production.",
            env_var, env_var,
        )
        priv = Ed25519PrivateKey.generate()
        seed = priv.private_bytes(
            Encoding.Raw, PrivateFormat.Raw, NoEncryption()
        )
        return cls.from_seed(seed)


# ── Attestation dataclass ───────────────────────────────────────

@dataclass(frozen=True)
class Attestation:
    """Cryptographic attestation binding a Certificate to a specific
    Veritas build and signer.

    ``request_digest`` is reserved for slice 4 (schema v2, request
    binding). In schema v1 it is always ``None`` and is omitted from
    both the wire JSON and the signed payload."""

    schema_version: int
    veritas_version: str
    build_sha: str
    public_key: str
    signed_at: str
    signature: str
    request_digest: str | None = None

    def to_json(self) -> dict:
        out: dict = {
            "schema_version": self.schema_version,
            "veritas_version": self.veritas_version,
            "build_sha": self.build_sha,
            "public_key": self.public_key,
            "signed_at": self.signed_at,
            "signature": self.signature,
        }
        if self.request_digest is not None:
            out["request_digest"] = self.request_digest
        return out

    @classmethod
    def from_json(cls, obj: dict) -> "Attestation":
        return cls(
            schema_version=int(obj["schema_version"]),
            veritas_version=str(obj["veritas_version"]),
            build_sha=str(obj["build_sha"]),
            public_key=str(obj["public_key"]),
            signed_at=str(obj["signed_at"]),
            signature=str(obj["signature"]),
            request_digest=obj.get("request_digest"),
        )


class AttestationError(ValueError):
    """Raised when an attestation fails verification."""


# ── Canonical payloads (each vN is FROZEN) ──────────────────────
#
# Rule: once ``_canonical_payload_vN`` ships, its body MUST NOT change.
# Changing it would silently invalidate every attestation ever issued
# under that schema version. Add ``_canonical_payload_v(N+1)`` with
# whatever shape you want next; wire it into sign/verify dispatch;
# leave prior versions untouched.

def _canonical_payload_v1(
    *,
    schema_version: int,
    veritas_version: str,
    build_sha: str,
    public_key: str,
    signed_at: str,
    certificate_body: dict,
) -> bytes:
    return canonical_json_bytes({
        "schema_version": schema_version,
        "veritas_version": veritas_version,
        "build_sha": build_sha,
        "public_key": public_key,
        "signed_at": signed_at,
        "certificate_body": certificate_body,
    })


def _canonical_payload_v2(
    *,
    schema_version: int,
    veritas_version: str,
    build_sha: str,
    public_key: str,
    signed_at: str,
    certificate_body: dict,
    request_digest: str,
) -> bytes:
    return canonical_json_bytes({
        "schema_version": schema_version,
        "veritas_version": veritas_version,
        "build_sha": build_sha,
        "public_key": public_key,
        "signed_at": signed_at,
        "certificate_body": certificate_body,
        "request_digest": request_digest,
    })


# ── Sign / verify (dispatch by schema version) ──────────────────

def sign_certificate_body(
    certificate_body: dict,
    signing_key: SigningKey,
    build_sha: str,
    request_digest: str,
    veritas_version: str = VERITAS_VERSION,
    now: datetime | None = None,
) -> Attestation:
    """Sign a certificate body and return an ``Attestation`` at the
    current schema version (v2: includes ``request_digest`` binding).

    ``certificate_body`` is the certificate's JSON dict EXCLUDING the
    ``attestation`` field (see ``Certificate.body_json()``).
    ``request_digest`` is the hex sha256 of the canonical JSON of
    the submitted ``(proposal, constraints, portfolio)``; compute it
    via :func:`compute_request_digest`."""
    ts = (now or datetime.now(timezone.utc))
    signed_at = ts.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    payload = _canonical_payload_v2(
        schema_version=CURRENT_SCHEMA_VERSION,
        veritas_version=veritas_version,
        build_sha=build_sha,
        public_key=signing_key.public_key_b64,
        signed_at=signed_at,
        certificate_body=certificate_body,
        request_digest=request_digest,
    )
    sig = signing_key.sign(payload)
    return Attestation(
        schema_version=CURRENT_SCHEMA_VERSION,
        veritas_version=veritas_version,
        build_sha=build_sha,
        public_key=signing_key.public_key_b64,
        signed_at=signed_at,
        signature=base64.b64encode(sig).decode("ascii"),
        request_digest=request_digest,
    )


def verify_certificate(
    certificate_body: dict,
    attestation: Attestation,
    *,
    expected_public_key: str | None = None,
    expected_request_digest: str | None = None,
) -> None:
    """Verify an attestation against a certificate body.

    Raises ``AttestationError`` on any failure; returns ``None`` on
    success.

    ``expected_public_key`` (base64): if provided, asserts the
    attestation was produced by that specific key.

    ``expected_request_digest`` (hex sha256): REQUIRED for schema v2
    attestations. The caller recomputes this from their own copy of
    the inputs using :func:`compute_request_digest` and passes it
    here; any mismatch (or omission) fails verification. This is the
    replay-protection guarantee v2 exists to provide — there is
    deliberately no opt-out. For schema v1 attestations the argument
    is ignored."""
    if attestation.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise AttestationError(
            f"unsupported schema_version {attestation.schema_version}; "
            f"this build supports {SUPPORTED_SCHEMA_VERSIONS}"
        )
    if (expected_public_key is not None
            and expected_public_key != attestation.public_key):
        raise AttestationError(
            "attestation public_key does not match expected key"
        )
    try:
        pub_raw = base64.b64decode(attestation.public_key, validate=True)
        sig_raw = base64.b64decode(attestation.signature, validate=True)
    except Exception as e:
        raise AttestationError(f"malformed base64 field: {e}") from e
    try:
        pk = Ed25519PublicKey.from_public_bytes(pub_raw)
    except Exception as e:
        raise AttestationError(f"malformed public key: {e}") from e
    if attestation.schema_version == 1:
        payload = _canonical_payload_v1(
            schema_version=attestation.schema_version,
            veritas_version=attestation.veritas_version,
            build_sha=attestation.build_sha,
            public_key=attestation.public_key,
            signed_at=attestation.signed_at,
            certificate_body=certificate_body,
        )
    elif attestation.schema_version == 2:
        if attestation.request_digest is None:
            raise AttestationError(
                "schema v2 attestation is missing request_digest"
            )
        if expected_request_digest is None:
            raise AttestationError(
                "schema v2 attestation requires expected_request_digest; "
                "compute via compute_request_digest(proposal, constraints, "
                "portfolio) and pass it in"
            )
        if expected_request_digest != attestation.request_digest:
            raise AttestationError(
                "request_digest does not match expected (replay attempt "
                "or input mismatch)"
            )
        payload = _canonical_payload_v2(
            schema_version=attestation.schema_version,
            veritas_version=attestation.veritas_version,
            build_sha=attestation.build_sha,
            public_key=attestation.public_key,
            signed_at=attestation.signed_at,
            certificate_body=certificate_body,
            request_digest=attestation.request_digest,
        )
    else:
        raise AttestationError(
            f"no verify path for schema_version {attestation.schema_version}"
        )
    try:
        pk.verify(sig_raw, payload)
    except InvalidSignature as e:
        raise AttestationError("signature does not verify") from e
