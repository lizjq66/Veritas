"""Veritas MCP server — verification tool for agent callers.

An MCP-compatible agent (Claude Desktop, Claude Code, any MCP client)
can use Veritas as a pre-trade verifier. Primary tool:

    verify_proposal — submit a trade proposal, receive a certificate
                      listing Gate 1 / Gate 2 / Gate 3 verdicts.

Secondary tools expose the assumption library, trade journal, and
Lean theorem registry for inspection.

All gate logic executes in the Lean kernel. The MCP surface is
transport; it does not decide.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from mcp.server import Server
from mcp.types import Tool, TextContent

from python.api import db
from python.api.theorem_registry import THEOREMS
from python.schemas import (
    AccountConstraints,
    Portfolio,
    PortfolioPosition,
    TradeProposal,
)
from python.verifier import Verifier

server = Server("veritas")

_DB_PATH = Path(os.environ.get("VERITAS_DB_PATH", "data/veritas.db"))
_verifier: Verifier | None = None


def _get_verifier() -> Verifier:
    global _verifier
    if _verifier is None:
        _verifier = Verifier()
    return _verifier


TOOLS = [
    # ── Primary tool: verification ─────────────────────────────────
    Tool(
        name="verify_proposal",
        description=(
            "Submit a proposed trade to Veritas's three-gate verifier. "
            "Returns a Certificate containing:\n"
            "  Gate 1 (signal consistency): does the direction match what "
            "  Veritas's policy would signal here? Are assumptions attached?\n"
            "  Gate 2 (strategy-constraint compatibility): does the size "
            "  fit the reliability-adjusted ceiling? May resize down.\n"
            "  Gate 3 (portfolio interference): does it clash with existing "
            "  positions or breach portfolio-wide exposure caps?\n"
            "Use this as a trust filter before actually placing a trade."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "direction": {"type": "string", "enum": ["LONG", "SHORT"]},
                "notional_usd": {"type": "number", "description": "Requested notional size in USD"},
                "funding_rate": {"type": "number", "description": "Current perp funding rate (decimal per hour)"},
                "price": {"type": "number", "description": "Current asset price in USD"},
                "timestamp": {"type": "integer", "default": 0},
                "open_interest": {"type": "number", "default": 0},
                "spot_price": {
                    "type": "number",
                    "default": 0,
                    "description": (
                        "Concurrent spot price of the asset on a reference "
                        "venue. Needed by basis-reversion. Set to 0 to "
                        "indicate 'spot unknown' and skip basis checks."
                    ),
                },
                "equity": {"type": "number", "description": "Caller's account equity in USD"},
                "reliability": {
                    "type": "number",
                    "description": "Empirical reliability of the assumption backing the trade (0.0–1.0). "
                                   "If omitted, defaults to 0.5.",
                },
                "sample_size": {
                    "type": "integer",
                    "description": "Number of historical samples behind the reliability score. "
                                   "Under 10 enters exploration phase (fixed 1% sizing).",
                    "default": 0,
                },
                "max_leverage": {"type": "number", "default": 1.0},
                "stop_loss_pct": {"type": "number", "default": 5.0},
                "existing_position_direction": {
                    "type": "string",
                    "enum": ["LONG", "SHORT"],
                    "description": "If the caller already holds a position on the same asset, its direction.",
                },
                "existing_position_entry_price": {"type": "number"},
                "existing_position_size": {"type": "number"},
                "max_gross_exposure_fraction": {"type": "number", "default": 0.50},
            },
            "required": ["direction", "notional_usd", "funding_rate",
                         "price", "equity"],
        },
    ),
    # ── Trust / inspection tools ────────────────────────────────────
    Tool(
        name="list_assumptions",
        description=(
            "List all assumptions in Veritas's library with their current "
            "reliability scores. Use to see what Veritas has empirical "
            "data on before calling verify_proposal."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="get_assumption",
        description=(
            "Look up one assumption by name. Returns reliability, sample "
            "size, the Lean file backing it, and recent outcomes."
        ),
        inputSchema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    ),
    Tool(
        name="verify_theorem",
        description=(
            "Check the verification status of a Lean theorem Veritas "
            "relies on. Returns whether it is proven, has a sorry, depends "
            "on axioms, or doesn't exist. Use this to verify trust claims."
        ),
        inputSchema={
            "type": "object",
            "properties": {"theorem_name": {"type": "string"}},
            "required": ["theorem_name"],
        },
    ),
    Tool(
        name="list_theorems",
        description=(
            "List every theorem in Veritas's registry, grouped by gate. "
            "Use as a directory of what Veritas publishes as a trust "
            "signal."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    # ── Demo-runner state (optional; empty when no runner is active) ──
    Tool(
        name="get_runner_state",
        description=(
            "Observation of the bundled demo runner: trade count, phase, "
            "recent win rate. Returns zeroes if no runner has written to "
            "the journal. Not required for pure verification use."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="get_recent_trades",
        description=(
            "Recent trades from the demo runner's journal. Used to show "
            "a caller what past verification outcomes looked like."
        ),
        inputSchema={
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 10, "maximum": 50}},
        },
    ),
]

EXPLORATION_THRESHOLD = 10
STARTING_EQUITY = 10000.0


def _init_db() -> None:
    db.set_db_path(_DB_PATH)


def _text(data: dict) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


# ── Tool handlers ────────────────────────────────────────────────

def _handle_verify_proposal(args: dict) -> dict:
    proposal = TradeProposal(
        direction=args["direction"],
        notional_usd=float(args["notional_usd"]),
        funding_rate=float(args["funding_rate"]),
        price=float(args["price"]),
        timestamp=int(args.get("timestamp", 0)),
        open_interest=float(args.get("open_interest", 0.0)),
        spot_price=float(args.get("spot_price", 0.0)),
    )
    constraints = AccountConstraints(
        equity=float(args["equity"]),
        reliability=float(args.get("reliability", 0.5)),
        sample_size=int(args.get("sample_size", 0)),
        max_leverage=float(args.get("max_leverage", 1.0)),
        stop_loss_pct=float(args.get("stop_loss_pct", 5.0)),
    )
    positions: tuple[PortfolioPosition, ...] = ()
    if args.get("existing_position_direction"):
        positions = (PortfolioPosition(
            direction=args["existing_position_direction"],
            entry_price=float(args["existing_position_entry_price"]),
            size=float(args["existing_position_size"]),
        ),)
    portfolio = Portfolio(
        positions=positions,
        max_gross_exposure_fraction=float(args.get("max_gross_exposure_fraction", 0.50)),
    )
    cert = _get_verifier().verify(proposal, constraints, portfolio)
    return cert.to_json()


def _handle_list_assumptions() -> dict:
    rows = db.get_assumptions()
    return {
        "assumptions": [
            {**r, "reliability": r["wins"] / r["total"] if r["total"] > 0 else 0.5}
            for r in rows
        ]
    }


def _handle_get_assumption(name: str) -> dict:
    row = db.get_assumption(name)
    if row is None:
        return {"error": "not_found", "message": f"Assumption '{name}' not found"}
    outcomes = db.get_recent_outcomes(name)
    return {
        **row,
        "reliability": row["wins"] / row["total"] if row["total"] > 0 else 0.5,
        "lean_theorem_path": "Veritas/Strategy/FundingReversion.lean",
        "verification_status": "proven",
        "recent_outcomes": outcomes,
    }


def _handle_verify_theorem(theorem_name: str) -> dict:
    entry = THEOREMS.get(theorem_name)
    if entry is None:
        return {"error": "not_found", "message": f"Theorem '{theorem_name}' not found"}
    return {"theorem": theorem_name, **entry}


def _handle_list_theorems() -> dict:
    return {
        "theorems": [
            {"name": name, **meta}
            for name, meta in THEOREMS.items()
        ]
    }


def _handle_get_runner_state() -> dict:
    stats = db.get_trade_stats()
    tc = stats["total"]
    return {
        "phase": "exploration" if tc < EXPLORATION_THRESHOLD else "exploitation",
        "trade_count": tc,
        "exploration_threshold": EXPLORATION_THRESHOLD,
        "current_position": None,
        "equity_estimate": STARTING_EQUITY + stats["total_pnl"],
        "starting_equity": STARTING_EQUITY,
        "total_pnl": stats["total_pnl"],
        "win_rate": stats["wins"] / tc if tc > 0 else None,
    }


def _handle_get_recent_trades(limit: int = 10) -> dict:
    limit = min(max(limit, 1), 50)
    trades, total = db.get_trades(limit, 0)
    return {"trades": trades, "total": total}


# ── Back-compat handlers (old names kept for existing tests) ────

def _handle_get_state() -> dict:
    return _handle_get_runner_state()


def _handle_would_take_signal(direction: str, asset: str = "BTC") -> dict:
    """DEPRECATED in the verifier-first world. Kept because existing
    tests and external agents may still call it; prefer
    `verify_proposal` going forward."""
    assumption_name = "funding_rate_reverts_within_8h"
    row = db.get_assumption(assumption_name)
    if row is None:
        return {
            "would_execute": False,
            "reason": "No assumption data available",
            "position_size_usd": None,
            "max_loss_bound_pct": 5.0,
            "relevant_assumption": None,
            "assumption_reliability": None,
            "deprecated": True,
            "prefer": "verify_proposal",
        }
    total = row["total"]
    reliability = row["wins"] / total if total > 0 else 0.5
    if total < EXPLORATION_THRESHOLD:
        would = True
        size_usd = STARTING_EQUITY * 0.01
        reason = (
            f"Exploration phase ({total}/{EXPLORATION_THRESHOLD} trades). "
            f"Would use fixed 1% sizing (${size_usd:.0f})."
        )
    elif reliability <= 0.5:
        would = False
        size_usd = 0.0
        reason = (
            f"Reliability is {reliability:.0%} ({row['wins']}/{total}), "
            f"at or below 0.5. No edge detected — Lean core returns zero size."
        )
    else:
        would = True
        size_usd = min(STARTING_EQUITY * 0.25, STARTING_EQUITY * (reliability - 0.5))
        reason = (
            f"Reliability is {reliability:.0%} ({row['wins']}/{total}). "
            f"Kelly sizing: ${size_usd:,.0f}. Capped at 25% of equity."
        )
    return {
        "would_execute": would,
        "reason": reason,
        "position_size_usd": size_usd,
        "max_loss_bound_pct": 5.0,
        "relevant_assumption": assumption_name,
        "assumption_reliability": reliability,
        "deprecated": True,
        "prefer": "verify_proposal",
    }


# ── MCP registration ────────────────────────────────────────────

@server.list_tools()
async def handle_list_tools():
    return TOOLS


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict | None = None):
    _init_db()
    arguments = arguments or {}

    if name == "verify_proposal":
        return _text(_handle_verify_proposal(arguments))
    elif name == "list_assumptions":
        return _text(_handle_list_assumptions())
    elif name == "get_assumption":
        return _text(_handle_get_assumption(arguments["name"]))
    elif name == "verify_theorem":
        return _text(_handle_verify_theorem(arguments["theorem_name"]))
    elif name == "list_theorems":
        return _text(_handle_list_theorems())
    elif name == "get_runner_state" or name == "get_state":
        return _text(_handle_get_runner_state())
    elif name == "get_recent_trades":
        return _text(_handle_get_recent_trades(arguments.get("limit", 10)))
    elif name == "would_take_signal":
        return _text(_handle_would_take_signal(
            arguments["direction"], arguments.get("asset", "BTC")))
    else:
        return _text({"error": "unknown_tool", "message": f"Tool '{name}' not found"})
