from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from python.api import db

router = APIRouter()


@router.get("/trades")
async def list_trades(
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    trades, total = db.get_trades(limit, offset)
    return {"trades": trades, "total": total}


@router.get("/trades/{trade_id}")
async def get_trade(trade_id: int) -> dict:
    trade = db.get_trade(trade_id)
    if trade is None:
        raise HTTPException(status_code=404, detail={"error": "not_found", "message": f"Trade {trade_id} not found"})
    return trade
