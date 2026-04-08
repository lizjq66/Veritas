"""Orchestration loop — the eight-step cycle.

This file contains NO decision logic. Every decision step calls the
Lean veritas-core binary via the bridge. Python only orchestrates I/O.

    1. observe  (Python)  → fetch market data
    2. decide   (Lean)    → should we trade?
    3. declare  (Lean)    → what are we betting on?
    4. check    (Python)  → look up assumption reliability from SQLite
    5. size     (Lean)    → how much to bet?
    6. execute  (Python)  → place the order
    7. monitor  (Lean)    → should we exit?
    8. learn    (Lean+Py) → update reliability, record trade
"""

import sys
import time
from datetime import datetime, timezone

from python.bridge import VeritasCore
from python.observer import FakeObserver
from python.executor import FakeExecutor
from python.journal import (
    init_db, seed_assumptions, get_assumption_stats,
    update_assumption_stats, ensure_assumption, record_trade, get_trade_count,
)


def run(*, fake: bool = True, interval: int = 5) -> None:
    core = VeritasCore()
    observer = FakeObserver() if fake else None
    executor = FakeExecutor() if fake else None

    if observer is None or executor is None:
        print("Real Hyperliquid connection not yet implemented.")
        sys.exit(1)

    init_db()
    seed_assumptions()

    position: dict | None = None

    # Banner
    n_trades = get_trade_count()
    sorry_count = 7  # tracked manually until we automate grep
    print()
    print("Veritas v0.1 | Lean-native core | BTC-USDC perp")
    print("\u2501" * 50)
    print(f"Core: veritas-core (Lean 4, compiled to native)")
    print(f"Unproven theorems: {sorry_count} ({sorry_count} sorries in Lean source)")
    print(f"Trades so far: {n_trades}")
    print()

    try:
        while True:
            snapshot = observer.snapshot()
            _log(f"observe \u2192 funding={snapshot['funding_rate']:+.6f}, "
                 f"price=${snapshot['btc_price']:,.0f}")

            if position is not None:
                # ── Steps 7-8: monitor → learn ──
                decision = core.monitor(snapshot, position)
                action = decision.get("action", "hold")

                if action == "exit":
                    reason = decision["reason"]
                    result = executor.close_position(snapshot["btc_price"])
                    pnl = result.get("pnl_pct", 0.0)
                    _log(f"exit    \u2192 {reason} (pnl {pnl:+.2f}%)")

                    # Step 8: learn — ask Lean for new stats
                    stats = get_assumption_stats(position["assumption_name"])
                    if stats:
                        new_stats = core.update_reliability(stats, reason)
                        update_assumption_stats(position["assumption_name"], new_stats)
                        _log(f"learn   \u2192 reliability "
                             f"{stats['wins']}/{stats['total']} \u2192 "
                             f"{new_stats['wins']}/{new_stats['total']} "
                             f"({new_stats['reliability']:.0%})")

                    # Record trade
                    record_trade(
                        entry_time=position["entry_time"],
                        direction=position["direction"],
                        entry_price=position["entry_price"],
                        size=position["size"],
                        assumption_name=position["assumption_name"],
                        exit_time=datetime.now(timezone.utc).isoformat(),
                        exit_price=snapshot["btc_price"],
                        exit_reason=reason,
                        pnl=pnl,
                    )
                    position = None
                    print()
                else:
                    _log(f"monitor \u2192 hold")
            else:
                # ── Steps 2-6: decide → execute ──
                signal = core.decide(snapshot)

                if signal is None:
                    _log("decide  \u2192 no signal")
                else:
                    _log(f"decide  \u2192 {signal['direction']}")

                    # Step 3: declare
                    assumptions = core.extract(signal)
                    if assumptions:
                        aname = assumptions[0]["name"]
                        ensure_assumption(aname, assumptions[0].get("description", ""))
                        _log(f"declare \u2192 \"{aname}\"")

                        # Step 4: check reliability from SQLite
                        stats = get_assumption_stats(aname) or {"wins": 0, "total": 0}
                        reliability = (
                            stats["wins"] / stats["total"]
                            if stats["total"] > 0 else 0.5
                        )
                        _log(f"check   \u2192 reliability {reliability:.0%} "
                             f"({stats['wins']}/{stats['total']})")

                        # Step 5: size (Lean decides)
                        equity = executor.equity()
                        sizing = core.size(equity, reliability)
                        pos_size = sizing["position_size"]

                        if pos_size <= 0:
                            _log(f"size    \u2192 0 (no edge, skipping)")
                        else:
                            _log(f"size    \u2192 ${pos_size:,.2f} of ${equity:,.0f}")

                            # Step 6: execute
                            stop_loss_pct = 5.0  # fixed for v0.1
                            leverage = 1.0
                            result = executor.open_position(
                                direction=signal["direction"],
                                size_usd=pos_size,
                                price=snapshot["btc_price"],
                                leverage=leverage,
                                stop_loss_pct=stop_loss_pct,
                                assumption_name=aname,
                                entry_timestamp=snapshot["timestamp"],
                            )
                            if result["ok"]:
                                position = {
                                    "direction": signal["direction"],
                                    "entry_price": result["price"],
                                    "size": result["size"],
                                    "leverage": leverage,
                                    "stop_loss_pct": stop_loss_pct,
                                    "entry_timestamp": snapshot["timestamp"],
                                    "assumption_name": aname,
                                    "entry_time": datetime.now(timezone.utc).isoformat(),
                                }
                                _log(f"execute \u2192 {signal['direction']} "
                                     f"{result['size']:.6f} BTC @ "
                                     f"${result['price']:,.0f}")
                            else:
                                _log(f"execute \u2192 FAILED: {result.get('error')}")
                        print()

            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nshutting down")


def _log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


if __name__ == "__main__":
    run()
