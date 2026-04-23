"""Veritas SDK — caller-side surface.

This module is the **public client API** of Veritas. Agents and other
external callers use it to:

- Build a request (``TradeProposal`` + ``AccountConstraints`` +
  ``Portfolio``) to send to a Veritas instance over HTTP or MCP.
- Decode the returned ``Certificate``.
- Independently verify the certificate's cryptographic ``Attestation``
  against a pinned signer, build hash, and (optionally) theorem
  registry hash — without trusting the Veritas operator, and without
  running the Lean kernel locally.

The module is deliberately ``veritas-core``-free: no ``.lake`` binary
dependency, no ``subprocess``, no ``python.bridge`` import. Everything
re-exported here works as pure Python over JSON/HTTP.

## Trust-on-first-use flow

A caller pins three values at integration time:

1. ``public_key``  — the Ed25519 key the operator advertises on
   ``GET /verify/pubkey``. The caller trusts this key.
2. ``build_sha``   — the sha256 of the ``veritas-core`` binary the
   operator is running. Exposed on ``/verify/pubkey``.
3. ``theorem_registry_sha`` — sha256 of the claimed theorem list
   (v0.3 Slice 5). Exposed on ``/verify/pubkey`` and
   ``/verify/theorems``.

On every subsequent verdict, the caller recomputes the request digest
from its own copy of the inputs and calls :func:`verify_certificate`.
Any tampering — to the verdict, to the signer, or to the inputs —
surfaces as an ``AttestationError``.

## Example

.. code-block:: python

    from python.sdk import (
        TradeProposal, AccountConstraints, Portfolio,
        Certificate, Attestation,
        compute_request_digest, verify_certificate, AttestationError,
    )

    # One-time setup: pin the values your ops team approved.
    PINNED_PUBLIC_KEY          = "..."   # base64 Ed25519
    PINNED_BUILD_SHA           = "..."   # sha256 hex
    # Per-call: build the request.
    proposal = TradeProposal(
        direction="LONG", notional_usd=1500.0,
        funding_rate=0.0012, price=68000.0, timestamp=0,
    )
    constraints = AccountConstraints(
        equity=10000.0, successes=16, failures=4,  # Beta(1,1) prior by default
    )
    portfolio = Portfolio()

    # Submit to Veritas (via your HTTP client of choice).
    response = http_client.post_json(
        "/verify/proposal",
        {"proposal": vars(proposal),
         "constraints": vars(constraints),
         "portfolio": None},
    )
    cert = Certificate.from_json(response)

    # Independent verification.
    digest = compute_request_digest(proposal, constraints, portfolio)
    try:
        verify_certificate(
            cert.body_json(), cert.attestation,
            expected_public_key=PINNED_PUBLIC_KEY,
            expected_request_digest=digest,
        )
    except AttestationError as e:
        raise SystemExit(f"Untrusted Veritas response: {e}")

    if cert.approves:
        submit_order_to_exchange(cert.final_notional_usd)
"""

from __future__ import annotations

from python.attestation import (
    Attestation,
    AttestationError,
    compute_request_digest,
    verify_certificate,
)
from python.schemas import (
    AccountConstraints,
    Certificate,
    CorrelationEntry,
    Portfolio,
    PortfolioPosition,
    TradeProposal,
    Verdict,
)

__all__ = [
    # Input types (what callers send to Veritas).
    "TradeProposal",
    "AccountConstraints",
    "Portfolio",
    "PortfolioPosition",
    "CorrelationEntry",
    # Output types (what callers receive from Veritas).
    "Certificate",
    "Verdict",
    "Attestation",
    # Verification surface.
    "compute_request_digest",
    "verify_certificate",
    "AttestationError",
]
