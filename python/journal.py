from __future__ import annotations

"""SQLite read/write — persistence for assumptions and trades.

Pure I/O: reads and writes data. No decisions.
The journal records what happened; Lean core decides what to do.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path("data/veritas.db")

ASSUMPTIONS_SEED = [
    {
        "name": "funding_rate_reverts_within_8h",
        "description": (
            "When |funding_rate| > 0.05%/hr on Hyperliquid BTC perp, "
            "it returns to |funding_rate| < 0.01%/hr within 8 hours."
        ),
    }
]

_conn: sqlite3.Connection | None = None


def _get_conn() -> sqlite3.Connection:
    if _conn is None:
        raise RuntimeError("Call init_db() first")
    return _conn


def init_db(db_path: Path = DB_PATH) -> None:
    """Create tables if they don't exist."""
    global _conn
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _conn = sqlite3.connect(str(db_path))
    _conn.row_factory = sqlite3.Row
    _conn.execute("PRAGMA foreign_keys = ON")
    _conn.executescript(
        "CREATE TABLE IF NOT EXISTS assumptions ("
        "  name         TEXT PRIMARY KEY,"
        "  description  TEXT NOT NULL,"
        "  wins         INTEGER NOT NULL DEFAULT 0,"
        "  total        INTEGER NOT NULL DEFAULT 0,"
        "  last_updated TIMESTAMP NOT NULL"
        ");"
        "CREATE TABLE IF NOT EXISTS trades ("
        "  id              INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  entry_time      TIMESTAMP NOT NULL,"
        "  exit_time       TIMESTAMP,"
        "  direction       TEXT NOT NULL CHECK (direction IN ('LONG', 'SHORT')),"
        "  entry_price     REAL NOT NULL,"
        "  exit_price      REAL,"
        "  size            REAL NOT NULL,"
        "  assumption_name TEXT NOT NULL,"
        "  exit_reason     TEXT CHECK (exit_reason IN"
        "                      ('assumption_met', 'assumption_broke', 'stop_loss')),"
        "  pnl             REAL,"
        "  FOREIGN KEY (assumption_name) REFERENCES assumptions(name)"
        ");"
    )
    _conn.commit()


def seed_assumptions() -> None:
    """Insert seed assumptions (no-op if they already exist)."""
    conn = _get_conn()
    now = _now()
    for a in ASSUMPTIONS_SEED:
        conn.execute(
            "INSERT OR IGNORE INTO assumptions (name, description, wins, total, last_updated) "
            "VALUES (?, ?, 0, 0, ?)",
            (a["name"], a["description"], now),
        )
    conn.commit()


def get_assumption_stats(name: str) -> dict | None:
    """Return {wins, total} for the named assumption, or None."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT wins, total FROM assumptions WHERE name = ?", (name,)
    ).fetchone()
    if row is None:
        return None
    return {"wins": row["wins"], "total": row["total"]}


def update_assumption_stats(name: str, new_stats: dict) -> None:
    """Overwrite wins/total for the named assumption."""
    conn = _get_conn()
    conn.execute(
        "UPDATE assumptions SET wins = ?, total = ?, last_updated = ? WHERE name = ?",
        (new_stats["wins"], new_stats["total"], _now(), name),
    )
    conn.commit()


def ensure_assumption(name: str, description: str = "") -> None:
    """Ensure the assumption exists in the DB."""
    conn = _get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO assumptions (name, description, wins, total, last_updated) "
        "VALUES (?, ?, 0, 0, ?)",
        (name, description, _now()),
    )
    conn.commit()


def record_trade(
    entry_time: str,
    direction: str,
    entry_price: float,
    size: float,
    assumption_name: str,
    exit_time: str | None = None,
    exit_price: float | None = None,
    exit_reason: str | None = None,
    pnl: float | None = None,
) -> int:
    """Insert a trade row. Returns the new trade id."""
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO trades "
        "(entry_time, exit_time, direction, entry_price, exit_price, "
        " size, assumption_name, exit_reason, pnl) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (entry_time, exit_time, direction, entry_price, exit_price,
         size, assumption_name, exit_reason, pnl),
    )
    conn.commit()
    return cur.lastrowid


def get_trade_count() -> int:
    return _get_conn().execute("SELECT COUNT(*) FROM trades").fetchone()[0]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
