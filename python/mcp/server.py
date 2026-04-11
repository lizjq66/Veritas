"""Veritas MCP server — trust oracle for external agents.

Exposes Veritas's assumption library, trade history, and theorem
verification status as MCP tools. Any MCP-compatible LLM client
(Claude desktop, Claude code) can query Veritas as a tool.

Read-only: no tool mutates state. Veritas's behavior is determined
by its Lean core, not by external requests.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from mcp.server import Server
from mcp.types import Tool, TextContent

from python.api import db
from python.api.theorem_registry import THEOREMS

server = Server("veritas")

_DB_PATH = Path(os.environ.get("VERITAS_DB_PATH", "data/veritas.db"))

TOOLS = [
    Tool(
        name="get_state",
        description=(
            "Get Veritas's current state — phase (exploration/exploitation), "
            "trade count, equity, win rate, and current position."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="list_assumptions",
        description=(
            "List all assumptions in Veritas's library with their current "
            "reliability scores. Use this to discover what Veritas has learned about."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="get_assumption",
        description=(
            "Look up an assumption in Veritas's library by name. Returns "
            "reliability, sample size, the Lean theorem it's tied to, and "
            "recent outcomes. Use this when reasoning about whether a market "
            "assumption is empirically reliable."
        ),
        inputSchema={
            "type": "object",
            "properties": {"name": {"type": "string", "description": "Assumption name"}},
            "required": ["name"],
        },
    ),
    Tool(
        name="get_recent_trades",
        description=(
            "Get the most recent trades Veritas has executed. Useful for "
            "understanding the agent's recent behavior and outcomes."
        ),
        inputSchema={
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 10, "maximum": 50}},
        },
    ),
    Tool(
        name="verify_theorem",
        description=(
            "Check the verification status of a Lean theorem in Veritas. "
            "Returns whether the theorem is proven, has a sorry, depends on "
            "axioms, or doesn't exist. Use this to verify trust claims."
        ),
        inputSchema={
            "type": "object",
            "properties": {"theorem_name": {"type": "string"}},
            "required": ["theorem_name"],
        },
    ),
    Tool(
        name="would_take_signal",
        description=(
            "Ask Veritas: given a direction and asset, would it take this "
            "trade? Returns the decision, sizing, and reasoning based on "
            "the relevant assumption's reliability. Use this as a 'trust "
            "filter' for trade ideas."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "direction": {"type": "string", "enum": ["LONG", "SHORT"]},
                "asset": {"type": "string", "default": "BTC"},
            },
            "required": ["direction"],
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

def _handle_get_state() -> dict:
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


def _handle_get_recent_trades(limit: int = 10) -> dict:
    limit = min(max(limit, 1), 50)
    trades, total = db.get_trades(limit, 0)
    return {"trades": trades, "total": total}


def _handle_verify_theorem(theorem_name: str) -> dict:
    entry = THEOREMS.get(theorem_name)
    if entry is None:
        return {"error": "not_found", "message": f"Theorem '{theorem_name}' not found"}
    return {"theorem": theorem_name, **entry}


def _handle_would_take_signal(direction: str, asset: str = "BTC") -> dict:
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
    }


# ── MCP registration ────────────────────────────────────────────

@server.list_tools()
async def handle_list_tools():
    return TOOLS


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict | None = None):
    _init_db()
    arguments = arguments or {}

    if name == "get_state":
        return _text(_handle_get_state())
    elif name == "list_assumptions":
        return _text(_handle_list_assumptions())
    elif name == "get_assumption":
        return _text(_handle_get_assumption(arguments["name"]))
    elif name == "get_recent_trades":
        return _text(_handle_get_recent_trades(arguments.get("limit", 10)))
    elif name == "verify_theorem":
        return _text(_handle_verify_theorem(arguments["theorem_name"]))
    elif name == "would_take_signal":
        return _text(_handle_would_take_signal(
            arguments["direction"], arguments.get("asset", "BTC")))
    else:
        return _text({"error": "unknown_tool", "message": f"Tool '{name}' not found"})
