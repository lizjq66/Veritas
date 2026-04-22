"""Verification endpoints — the primary API surface.

A calling agent POSTs a proposal and receives a certificate. All gate
logic executes in the Lean kernel; the API is a thin transport.

Theorem lookup (`GET /verify/theorem/{name}`) is retained for trust
inspection: callers can confirm which theorems are proved vs. sorry vs.
axiom.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from python.api.theorem_registry import THEOREMS
from python.schemas import (
    AccountConstraints,
    Portfolio,
    PortfolioPosition,
    TradeProposal,
)
from python.verifier import Verifier

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
    equity: float = Field(gt=0)
    reliability: float = Field(ge=0, le=1)
    sample_size: int = Field(ge=0)
    max_leverage: float = 1.0
    max_position_fraction: float = 0.25
    stop_loss_pct: float = 5.0
    daily_var_limit: float = Field(default=0.0, ge=0)


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
        reliability=c.reliability,
        sample_size=c.sample_size,
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
    and schema version. Callers fetch this once (trust-on-first-use)
    and verify every subsequent Certificate's attestation against
    the same key."""
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
        "veritas_version": VERITAS_VERSION,
        "schema_version": CURRENT_SCHEMA_VERSION,
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
