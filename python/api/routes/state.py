from __future__ import annotations

from fastapi import APIRouter

from python.api import db

router = APIRouter()

EXPLORATION_THRESHOLD = 10
STARTING_EQUITY = 10000.0


@router.get("/state")
async def get_state() -> dict:
    stats = db.get_trade_stats()
    trade_count = stats["total"]
    win_rate = stats["wins"] / trade_count if trade_count > 0 else None

    return {
        "phase": "exploration" if trade_count < EXPLORATION_THRESHOLD else "exploitation",
        "trade_count": trade_count,
        "exploration_threshold": EXPLORATION_THRESHOLD,
        "current_position": None,
        "equity_estimate": STARTING_EQUITY + stats["total_pnl"],
        "starting_equity": STARTING_EQUITY,
        "total_pnl": stats["total_pnl"],
        "win_rate": win_rate,
        "last_event_at": None,
    }
