"""Schemas for the Veritas verifier surface.

A calling trading agent talks to Veritas with three pieces of input:

    TradeProposal         — what the agent wants to do
    AccountConstraints    — policy envelope the trade must live inside
    Portfolio             — existing positions the trade must not clash with

and receives one piece of output:

    Certificate           — verdict per gate, attached assumptions,
                            final approved notional, reason codes

These schemas are deliberately small. They are the contract between the
Python adapter layer and the Lean verification kernel.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Direction = Literal["LONG", "SHORT"]
VerdictTag = Literal["approve", "resize", "reject"]


@dataclass(frozen=True)
class TradeProposal:
    """A proposed trade submitted to Veritas for verification."""

    direction: Direction
    notional_usd: float
    funding_rate: float
    price: float
    timestamp: int
    open_interest: float = 0.0


@dataclass(frozen=True)
class AccountConstraints:
    """Account-level policy envelope. Reliability is the empirical score
    for the assumption the caller attributes to this proposal."""

    equity: float
    reliability: float
    sample_size: int
    max_leverage: float = 1.0
    max_position_fraction: float = 0.25
    stop_loss_pct: float = 5.0


@dataclass(frozen=True)
class PortfolioPosition:
    """A thin summary of one existing position. v0.1 treats all positions
    as being on the same asset as the proposal."""

    direction: Direction
    entry_price: float
    size: float


@dataclass(frozen=True)
class Portfolio:
    """Existing positions plus the portfolio-level exposure cap."""

    positions: tuple[PortfolioPosition, ...] = ()
    max_gross_exposure_fraction: float = 0.50


@dataclass(frozen=True)
class Verdict:
    """Machine-readable verdict from a single gate."""

    tag: VerdictTag
    new_notional_usd: float | None = None
    reason_codes: tuple[str, ...] = ()

    @property
    def is_approve(self) -> bool:
        return self.tag == "approve"

    @property
    def is_reject(self) -> bool:
        return self.tag == "reject"

    @classmethod
    def from_json(cls, obj: dict) -> "Verdict":
        tag = obj["verdict"]
        if tag == "approve":
            return cls(tag="approve")
        if tag == "resize":
            return cls(tag="resize", new_notional_usd=float(obj["new_notional_usd"]))
        if tag == "reject":
            return cls(tag="reject", reason_codes=tuple(obj.get("reason_codes", ())))
        raise ValueError(f"unknown verdict tag: {tag!r}")

    def to_json(self) -> dict:
        out: dict = {"verdict": self.tag}
        if self.tag == "resize":
            out["new_notional_usd"] = self.new_notional_usd
        if self.tag == "reject":
            out["reason_codes"] = list(self.reason_codes)
        return out


@dataclass(frozen=True)
class Certificate:
    """The full result of running a proposal through all three gates."""

    gate1: Verdict
    gate2: Verdict
    gate3: Verdict
    assumptions: tuple[dict, ...]
    final_notional_usd: float
    approves: bool

    def to_json(self) -> dict:
        return {
            "gate1": self.gate1.to_json(),
            "gate2": self.gate2.to_json(),
            "gate3": self.gate3.to_json(),
            "assumptions": list(self.assumptions),
            "final_notional_usd": self.final_notional_usd,
            "approves": self.approves,
        }

    @classmethod
    def from_json(cls, obj: dict) -> "Certificate":
        return cls(
            gate1=Verdict.from_json(obj["gate1"]),
            gate2=Verdict.from_json(obj["gate2"]),
            gate3=Verdict.from_json(obj["gate3"]),
            assumptions=tuple(obj.get("assumptions", ())),
            final_notional_usd=float(obj["final_notional_usd"]),
            approves=_parse_approves(obj.get("approves", False)),
        )


def _parse_approves(v: object) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.lower() == "true"
    return bool(v)
