"""Verification endpoints — the primary API surface.

A calling agent POSTs a proposal and receives a certificate. All gate
logic executes in the Lean kernel; the API is a thin transport.

Theorem lookup (`GET /verify/theorem/{name}`) is retained for trust
inspection: callers can confirm which theorems are proved vs. sorry vs.
axiom.
"""

from __future__ import annotations

import warnings
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

from python.api.theorem_registry import THEOREMS
from python.schemas import (
    AccountConstraints,
    Portfolio,
    PortfolioPosition,
    TradeProposal,
)
from python.verifier import Verifier


# Flipped once per process the first time a caller submits the legacy
# `reliability` / `sample_size` fields. Scheduled for removal in v0.5;
# see CHANGELOG.md.
_LEGACY_RELIABILITY_WARNED = False


def _warn_legacy_reliability_once() -> None:
    global _LEGACY_RELIABILITY_WARNED
    if _LEGACY_RELIABILITY_WARNED:
        return
    _LEGACY_RELIABILITY_WARNED = True
    warnings.warn(
        "Veritas API: `reliability` / `sample_size` fields on "
        "/verify/proposal (and siblings) are deprecated as of v0.4. "
        "They are translated into the Bayesian "
        "`(successes, failures, prior_alpha, prior_beta)` tuple with a "
        "default Beta(1, 1) prior. Removal is scheduled for v0.5; "
        "migrate callers now. See CHANGELOG.md.",
        DeprecationWarning, stacklevel=3,
    )

router = APIRouter()

_verifier: Verifier | None = None


def _get_verifier() -> Verifier:
    global _verifier
    if _verifier is None:
        _verifier = Verifier()
    return _verifier


# ── Request / response models ────────────────────────────────────────

class ProposalIn(BaseModel):
    direction: Literal["LONG", "SHORT"]
    notional_usd: float = Field(gt=0)
    funding_rate: float
    price: float = Field(gt=0)
    timestamp: int = 0
    open_interest: float = 0.0
    spot_price: float = 0.0
    liquidations24h: float = 0.0
    asset: str = ""
    volatility: float = Field(default=0.0, ge=0)


class ConstraintsIn(BaseModel):
    """HTTP wire shape for `AccountConstraints`.

    The canonical reliability input is Bayesian
    `(successes, failures, prior_alpha, prior_beta)`. The legacy
    v0.3 `reliability` / `sample_size` pair is still accepted
    (deprecated; scheduled for removal in v0.5 — see CHANGELOG.md),
    translated at validation time into the Bayesian fields via a
    Beta(1, 1) prior."""

    equity: float = Field(gt=0)
    # v0.4 canonical fields
    successes: int = Field(default=0, ge=0)
    failures: int = Field(default=0, ge=0)
    prior_alpha: float = Field(default=1.0, ge=0)
    prior_beta: float = Field(default=1.0, ge=0)
    max_leverage: float = 1.0
    max_position_fraction: float = 0.25
    stop_loss_pct: float = 5.0
    daily_var_limit: float = Field(default=0.0, ge=0)
    # v0.3 legacy fields (deprecated; translated below)
    reliability: float | None = Field(default=None, ge=0, le=1)
    sample_size: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _translate_legacy_reliability(self) -> "ConstraintsIn":
        """When caller supplies legacy `(reliability, sample_size)`
        and has not independently set the Bayesian fields, derive
        `(successes, failures)` under a uniform prior and emit a
        one-shot deprecation warning."""
        caller_sent_legacy = (
            self.reliability is not None or self.sample_size is not None
        )
        caller_sent_bayesian = (
            self.successes > 0 or self.failures > 0
            or self.prior_alpha != 1.0 or self.prior_beta != 1.0
        )
        if caller_sent_legacy and not caller_sent_bayesian:
            _warn_legacy_reliability_once()
            rel = self.reliability if self.reliability is not None else 0.5
            total = self.sample_size if self.sample_size is not None else 0
            succ = round(rel * total)
            fail = total - succ
            object.__setattr__(self, "successes", succ)
            object.__setattr__(self, "failures", fail)
            # priors stay at Beta(1, 1) default
        return self


class PositionIn(BaseModel):
    direction: Literal["LONG", "SHORT"]
    entry_price: float = Field(gt=0)
    size: float = Field(gt=0)
    asset: str = ""
    volatility: float = Field(default=0.0, ge=0)


class CorrelationIn(BaseModel):
    asset_a: str
    asset_b: str
    coefficient: float


class PortfolioIn(BaseModel):
    positions: list[PositionIn] = Field(default_factory=list)
    max_gross_exposure_fraction: float = 0.50
    correlations: list[CorrelationIn] = Field(default_factory=list)


class VerifyRequest(BaseModel):
    proposal: ProposalIn
    constraints: ConstraintsIn
    portfolio: PortfolioIn | None = None


# ── Helpers ──────────────────────────────────────────────────────────

def _to_proposal(p: ProposalIn) -> TradeProposal:
    return TradeProposal(
        direction=p.direction,
        notional_usd=p.notional_usd,
        funding_rate=p.funding_rate,
        price=p.price,
        timestamp=p.timestamp,
        open_interest=p.open_interest,
        spot_price=p.spot_price,
        liquidations24h=p.liquidations24h,
        asset=p.asset,
        volatility=p.volatility,
    )


def _to_constraints(c: ConstraintsIn) -> AccountConstraints:
    return AccountConstraints(
        equity=c.equity,
        successes=c.successes,
        failures=c.failures,
        prior_alpha=c.prior_alpha,
        prior_beta=c.prior_beta,
        max_leverage=c.max_leverage,
        max_position_fraction=c.max_position_fraction,
        stop_loss_pct=c.stop_loss_pct,
        daily_var_limit=c.daily_var_limit,
    )


def _to_portfolio(p: PortfolioIn | None) -> Portfolio:
    if p is None:
        return Portfolio()
    from python.schemas import CorrelationEntry
    return Portfolio(
        positions=tuple(
            PortfolioPosition(direction=pos.direction,
                              entry_price=pos.entry_price,
                              size=pos.size,
                              asset=pos.asset,
                              volatility=pos.volatility)
            for pos in p.positions
        ),
        max_gross_exposure_fraction=p.max_gross_exposure_fraction,
        correlations=tuple(
            CorrelationEntry(asset_a=c.asset_a, asset_b=c.asset_b,
                             coefficient=c.coefficient)
            for c in p.correlations
        ),
    )


# ── Routes ──────────────────────────────────────────────────────────

@router.post("/verify/proposal")
async def verify_proposal(req: VerifyRequest) -> dict:
    """Run a proposal through all three gates and return a certificate."""
    v = _get_verifier()
    cert = v.verify(
        _to_proposal(req.proposal),
        _to_constraints(req.constraints),
        _to_portfolio(req.portfolio),
    )
    return cert.to_json()


@router.get("/verify/pubkey")
async def verify_pubkey() -> dict:
    """Return the Verifier's Ed25519 public key, attested build sha,
    pinned theorem-registry sha, and schema version. Callers fetch
    this once (trust-on-first-use) and verify every subsequent
    Certificate's attestation against the same key, optionally
    cross-checking ``build_sha`` and ``theorem_registry_sha`` against
    a pinned snapshot they trust."""
    from python.api.theorem_registry import compute_theorem_registry_sha
    from python.attestation import CURRENT_SCHEMA_VERSION, VERITAS_VERSION

    v = _get_verifier()
    pk = v.public_key
    if pk is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "signing_disabled",
                "message": "this verifier instance is not signing certificates",
            },
        )
    return {
        "algorithm": "ed25519",
        "public_key": pk,
        "build_sha": v.build_sha,
        "theorem_registry_sha": compute_theorem_registry_sha(),
        "veritas_version": VERITAS_VERSION,
        "schema_version": CURRENT_SCHEMA_VERSION,
    }


@router.get("/verify/theorems")
async def verify_theorems() -> dict:
    """Return the full theorem registry along with its pinned sha256.

    This is the bulk of what ``/verify/pubkey`` summarizes by hash.
    Callers who want to audit "does this build_sha actually claim to
    prove the theorems I need" fetch this endpoint once, inspect the
    list, and pin the returned ``theorem_registry_sha`` alongside
    ``build_sha`` at trust-setup time."""
    from python.api.theorem_registry import (
        THEOREMS,
        compute_theorem_registry_sha,
    )
    return {
        "theorem_registry_sha": compute_theorem_registry_sha(),
        "count": len(THEOREMS),
        "theorems": THEOREMS,
    }


@router.post("/verify/signal")
async def verify_signal(req: VerifyRequest) -> dict:
    """Run Gate 1 only: signal / assumption consistency."""
    v = _get_verifier()
    verdict, assumptions = v.verify_signal(_to_proposal(req.proposal))
    return {
        "gate": 1,
        "name": "signal_consistency",
        "result": verdict.to_json(),
        "assumptions": list(assumptions),
    }


@router.post("/verify/constraints")
async def verify_constraints(req: VerifyRequest) -> dict:
    """Run Gate 2 only: strategy-constraint compatibility."""
    v = _get_verifier()
    verdict = v.check_constraints(
        _to_proposal(req.proposal), _to_constraints(req.constraints)
    )
    return {
        "gate": 2,
        "name": "strategy_constraint_compatibility",
        "result": verdict.to_json(),
    }


@router.post("/verify/portfolio")
async def verify_portfolio(req: VerifyRequest) -> dict:
    """Run Gate 3 only: portfolio interference."""
    v = _get_verifier()
    verdict = v.check_portfolio(
        _to_proposal(req.proposal),
        _to_portfolio(req.portfolio),
        req.constraints.equity,
        req.constraints.daily_var_limit,
    )
    return {
        "gate": 3,
        "name": "portfolio_interference",
        "result": verdict.to_json(),
    }


@router.get("/verify/theorem/{theorem_name}")
async def verify_theorem(theorem_name: str) -> dict:
    """Look up the verification status of a named Lean theorem."""
    entry = THEOREMS.get(theorem_name)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found",
                    "message": f"Theorem '{theorem_name}' not found"})
    return {"theorem": theorem_name, **entry}


# Backward-compatible alias: older clients hit GET /verify/{theorem_name}.
@router.get("/verify/{theorem_name}")
async def verify_theorem_legacy(theorem_name: str) -> dict:
    return await verify_theorem(theorem_name)
