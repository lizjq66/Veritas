"""Read-only database access for the API layer.

Opens the SQLite journal in read-only mode — physical enforcement
of the trust boundary. The API can observe but never mutate.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

_DB_PATH = Path(os.environ.get("VERITAS_DB_PATH", "data/veritas.db"))


def _connect() -> sqlite3.Connection:
    uri = f"file:{_DB_PATH}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def set_db_path(path: Path) -> None:
    """Override DB path (for testing)."""
    global _DB_PATH
    _DB_PATH = path


def get_assumptions() -> list[dict]:
    conn = _connect()
    rows = [dict(r) for r in conn.execute("SELECT * FROM assumptions ORDER BY name").fetchall()]
    conn.close()
    return rows


def get_assumption(name: str) -> dict | None:
    conn = _connect()
    row = conn.execute("SELECT * FROM assumptions WHERE name = ?", (name,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_trades(limit: int = 10, offset: int = 0) -> tuple[list[dict], int]:
    conn = _connect()
    total = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM trades ORDER BY id DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()]
    conn.close()
    return rows, total


def get_trade(trade_id: int) -> dict | None:
    conn = _connect()
    row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_recent_outcomes(assumption_name: str, limit: int = 10) -> list[dict]:
    conn = _connect()
    rows = conn.execute(
        "SELECT id, exit_reason, exit_time FROM trades "
        "WHERE assumption_name = ? AND exit_reason IS NOT NULL "
        "ORDER BY id DESC LIMIT ?",
        (assumption_name, limit),
    ).fetchall()
    conn.close()
    outcome_map = {"assumption_met": "met", "assumption_broke": "broke", "stop_loss": "stop_loss"}
    return [
        {"trade_id": r["id"], "outcome": outcome_map.get(r["exit_reason"], r["exit_reason"]),
         "timestamp": r["exit_time"]}
        for r in rows
    ]


def get_trade_stats() -> dict:
    """Aggregate trade statistics."""
    conn = _connect()
    row = conn.execute(
        "SELECT COUNT(*) as total, "
        "SUM(CASE WHEN exit_reason = 'assumption_met' THEN 1 ELSE 0 END) as wins, "
        "SUM(CASE WHEN pnl IS NOT NULL THEN pnl ELSE 0 END) as total_pnl "
        "FROM trades WHERE exit_reason IS NOT NULL"
    ).fetchone()
    conn.close()
    return {"total": row["total"], "wins": row["wins"] or 0, "total_pnl": row["total_pnl"] or 0.0}
