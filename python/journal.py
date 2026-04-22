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
    },
    {
        "name": "basis_reverts_within_24h",
        "description": (
            "When the BTC perp--spot basis exceeds ±0.20% on Hyperliquid "
            "vs the reference spot venue, it returns to within ±0.05% "
            "of zero inside 24 hours."
        ),
    },
    {
        "name": "price_reverts_after_liquidation_cascade_within_4h",
        "description": (
            "After |liquidations24h| exceeds $50M on Hyperliquid BTC "
            "perp, price reverts at least halfway toward the "
            "pre-cascade level within 4 hours."
        ),
    },
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
        "  source          TEXT NOT NULL DEFAULT 'testnet'"
        "                      CHECK (source IN ('mock', 'testnet', 'mainnet')),"
        "  entry_context   TEXT,"
        "  regime_tag      TEXT CHECK (regime_tag IN"
        "                      ('bull', 'bear', 'choppy', 'unknown')),"
        "  signal_correct  INTEGER,"
        "  slippage_bps    REAL,"
        "  fill_delay_ms   INTEGER,"
        "  realized_vs_expected_pnl REAL,"
        "  price_impact_bps REAL,"
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


def get_assumption_stats_many(names: "list[str] | tuple[str, ...]") -> dict:
    """Batch version for v0.2 multi-assumption Gate 1 output.
    Returns ``{name: {wins, total}}`` with missing rows defaulted to
    ``{wins: 0, total: 0}`` so a brand-new assumption does not break
    aggregate_reliability callers."""
    conn = _get_conn()
    placeholders = ",".join("?" for _ in names)
    rows = conn.execute(
        f"SELECT name, wins, total FROM assumptions WHERE name IN ({placeholders})",
        tuple(names),
    ).fetchall() if names else []
    by_name = {r["name"]: {"wins": r["wins"], "total": r["total"]} for r in rows}
    return {n: by_name.get(n, {"wins": 0, "total": 0}) for n in names}


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
    *,
    source: str = "testnet",
    entry_context: str | None = None,
    regime_tag: str | None = None,
    signal_correct: bool | None = None,
    slippage_bps: float | None = None,
    fill_delay_ms: int | None = None,
    realized_vs_expected_pnl: float | None = None,
    price_impact_bps: float | None = None,
) -> int:
    """Insert a trade row. Returns the new trade id."""
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO trades "
        "(entry_time, exit_time, direction, entry_price, exit_price, "
        " size, assumption_name, exit_reason, pnl, "
        " source, entry_context, regime_tag, signal_correct, "
        " slippage_bps, fill_delay_ms, realized_vs_expected_pnl, price_impact_bps) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (entry_time, exit_time, direction, entry_price, exit_price,
         size, assumption_name, exit_reason, pnl,
         source, entry_context, regime_tag,
         int(signal_correct) if signal_correct is not None else None,
         slippage_bps, fill_delay_ms, realized_vs_expected_pnl, price_impact_bps),
    )
    conn.commit()
    return cur.lastrowid


def get_trade_count() -> int:
    return _get_conn().execute("SELECT COUNT(*) FROM trades").fetchone()[0]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
