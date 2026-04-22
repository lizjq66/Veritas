"""Veritas verifier — the canonical entry point.

A calling trading agent asks Veritas to check a proposed trade through
the three gates. Veritas returns a Certificate. The verifier owns no
trading logic and makes no I/O calls beyond invoking the Lean kernel.

Usage:

    from python.verifier import Verifier
    from python.schemas import TradeProposal, AccountConstraints, Portfolio

    v = Verifier()
    cert = v.verify(proposal, constraints, portfolio)
    if cert.approves:
        ...            # submit `cert.final_notional_usd` to your exchange
    else:
        reasons = (cert.gate1.reason_codes
                   + cert.gate2.reason_codes
                   + cert.gate3.reason_codes)
        ...            # surface reasons to the caller; do not override

The Verifier is a thin wrapper over the Lean veritas-core binary. It
exposes the three gates individually (`verify_signal`, `check_constraints`,
`check_portfolio`) as well as the combined certificate (`verify`).

Python holds no gate logic. Every approve / resize / reject decision
flows through the Lean kernel. If you find yourself reimplementing a
check here, push it to Lean instead and re-expose it via this module.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from python.attestation import (
    SigningKey,
    compute_build_sha,
    compute_request_digest,
    sign_certificate_body,
)
from python.bridge import VeritasCore
from python.schemas import (
    AccountConstraints,
    Certificate,
    Portfolio,
    TradeProposal,
    Verdict,
)


class Verifier:
    """Canonical verification surface. Thin wrapper over VeritasCore.

    Every Certificate returned by ``verify()`` carries an Attestation
    signed by the Verifier's Ed25519 key (loaded from
    ``VERITAS_SIGNING_KEY`` or generated ephemerally with a warning)
    and bound to the sha256 of the ``veritas-core`` binary in use.
    Callers can verify these via ``python.attestation.verify_certificate``.
    Pass ``sign_certificates=False`` to opt out (e.g. for unit tests
    that compare raw verdicts)."""

    def __init__(
        self,
        core: VeritasCore | None = None,
        *,
        signing_key: SigningKey | None = None,
        sign_certificates: bool = True,
    ) -> None:
        self._core = core or VeritasCore()
        self._sign = sign_certificates
        if self._sign:
            self._signing_key = signing_key or SigningKey.from_env()
            self._build_sha = compute_build_sha(Path(self._core.binary))
        else:
            self._signing_key = None
            self._build_sha = None

    @property
    def public_key(self) -> str | None:
        """Base64 Ed25519 public key used to sign attestations, or
        ``None`` if signing is disabled."""
        return self._signing_key.public_key_b64 if self._signing_key else None

    @property
    def build_sha(self) -> str | None:
        """sha256 of the ``veritas-core`` binary attested in
        signatures, or ``None`` if signing is disabled."""
        return self._build_sha

    # ── Single-gate interfaces ─────────────────────────────────

    def verify_signal(self, p: TradeProposal) -> tuple[Verdict, tuple[dict, ...]]:
        """Gate 1: signal / assumption consistency."""
        obj = self._core.verify_signal(p)
        verdict = Verdict.from_json(obj["result"])
        assumptions = tuple(obj.get("assumptions", ()))
        return verdict, assumptions

    def check_constraints(
        self, p: TradeProposal, c: AccountConstraints
    ) -> Verdict:
        """Gate 2: strategy-constraint compatibility."""
        obj = self._core.check_constraints(p, c)
        return Verdict.from_json(obj["result"])

    def check_portfolio(
        self,
        p: TradeProposal,
        port: Portfolio,
        equity: float,
        daily_var_limit: float = 0.0,
    ) -> Verdict:
        """Gate 3: portfolio interference.

        ``daily_var_limit`` (default 0.0) enables the linear-VaR upper-bound
        check when set to a positive value. Leaving it at 0 preserves the
        v0.2 single-check behavior (gross-exposure cap only)."""
        obj = self._core.check_portfolio(p, port, equity, daily_var_limit)
        return Verdict.from_json(obj["result"])

    # ── Combined ─────────────────────────────────────────────────

    def verify(
        self,
        proposal: TradeProposal,
        constraints: AccountConstraints,
        portfolio: Portfolio | None = None,
    ) -> Certificate:
        """Run all three gates and return a Certificate.

        The gates execute in order: Gate 1 → Gate 2 → Gate 3. A Gate 2
        resize is visible to Gate 3. If any gate rejects, downstream
        gates receive ``upstream_gate_rejected`` and the final notional
        is zero.
        """
        port = portfolio or Portfolio()
        obj = self._core.emit_certificate(proposal, constraints, port)
        cert = Certificate.from_json(obj)
        if not self._sign:
            return cert
        request_digest = compute_request_digest(proposal, constraints, port)
        attestation = sign_certificate_body(
            cert.body_json(),
            signing_key=self._signing_key,
            build_sha=self._build_sha,
            request_digest=request_digest,
        )
        return replace(cert, attestation=attestation)
