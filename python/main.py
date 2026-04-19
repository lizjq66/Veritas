from __future__ import annotations

"""Example runner — funding-reversion demo loop.

This file is NOT the Veritas product. It is a reference example that
shows what a trading agent looks like when it sits behind the Veritas
verifier. The verifier is the product (see `python/verifier.py`). This
runner exists so new readers have a concrete picture of a caller.

The runner glues together:

    - an observer adapter (FakeObserver / HyperliquidObserver)
    - an executor adapter (FakeExecutor / HyperliquidExecutor)
    - the Veritas core (via `bridge.VeritasCore`)

It contains NO decision logic. Every decision step calls the Lean
verification kernel via the bridge. Python only orchestrates I/O.

    1. observe         (adapter) → fetch market data
    2. decide          (Lean)    → would Veritas's policy fire here?
    3. declare         (Lean)    → attach assumptions to the signal
    4. check           (adapter) → look up assumption reliability
    5. size            (Lean)    → Gate 2 ceiling
    6. execute         (adapter) → place the order at or below ceiling
    7. classify-exit   (Lean)    → should the open position close?
    8. learn           (Lean+Py) → update reliability, record trade

Apps that want only the verifier (no runner, no exchange) should import
`python.verifier.Verifier` directly and skip this module.
"""

import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from python.bridge import VeritasCore
from python.observer import FakeObserver
from python.executor import FakeExecutor
from python import journal


def run_loop(
    *,
    observer,
    executor,
    core: VeritasCore,
    db_path: Path = Path("data/veritas.db"),
    max_cycles: int = 0,
    clock: Callable[[], str] | None = None,
    log_fn: Callable[[str], None] | None = None,
    on_event: Callable[[dict], None] | None = None,
) -> dict:
    """Run the 8-step loop with injected dependencies.

    Returns a summary dict: {trades, cycles, final_stats}.
    """
    if clock is None:
        clock = lambda: datetime.now().strftime("%H:%M:%S")

    def _log(msg: str) -> None:
        line = f"[{clock()}] {msg}"
        if log_fn is not None:
            log_fn(line)
        else:
            print(line)

    def _print(msg: str = "") -> None:
        if log_fn is not None:
            log_fn(msg)
        else:
            print(msg)

    def _emit(event_type: str, **payload: object) -> None:
        if on_event is not None:
            on_event({"type": event_type, "timestamp": clock(), **payload})

    journal.init_db(db_path)
    journal.seed_assumptions()

    position: dict | None = None
    trades_completed = 0
    cycle = 0

    # Banner
    n_trades = journal.get_trade_count()
    _print()
    _print("Veritas v0.1 | funding-reversion example runner")
    _print("\u2501" * 50)
    _print("Verifier: veritas-core (Lean 4, compiled to native)")
    _print("Gates: 1 signal_consistency | 2 constraints | 3 portfolio")
    _print(f"Trades so far: {n_trades}")
    _print()

    while True:
        cycle += 1
        if max_cycles > 0 and cycle > max_cycles:
            break

        snapshot = observer.snapshot()
        _log(f"observe \u2192 funding={snapshot['funding_rate']:+.6f}, "
             f"price=${snapshot['btc_price']:,.0f}")
        _emit("observe", snapshot=snapshot)

        if position is not None:
            # ── Steps 7-8: monitor → learn ──
            decision = core.monitor(snapshot, position)
            action = decision.get("action", "hold")

            if action == "exit":
                reason = decision["reason"]
                result = executor.close_position(snapshot["btc_price"])
                pnl = result.get("pnl_pct", 0.0)
                _log(f"exit    \u2192 {reason} (pnl {pnl:+.2f}%)")
                _emit("execute_close", reason=reason, pnl=pnl, exit_price=snapshot["btc_price"])

                # Step 8: learn — ask Lean for new stats
                stats = journal.get_assumption_stats(position["assumption_name"])
                if stats:
                    new_stats = core.update_reliability(stats, reason)
                    journal.update_assumption_stats(position["assumption_name"], new_stats)
                    _log(f"learn   \u2192 reliability "
                         f"{stats['wins']}/{stats['total']} \u2192 "
                         f"{new_stats['wins']}/{new_stats['total']} "
                         f"({new_stats['reliability']:.0%})")
                    _emit("learn", assumption=position["assumption_name"],
                          old_stats=stats, new_stats=new_stats)

                # Compute execution quality via Lean core (Improvement 1.2)
                import json as _json
                mark_at_entry = position.get("mark_price_at_entry", position["entry_price"])
                fill_at_entry = position.get("fill_price", position["entry_price"])
                fill_delay = int(time.time() * 1000) - position.get("entry_ts_ms", 0)

                sig_correct = core.judge_signal(reason)
                eq = core.execution_quality(
                    mark_at_entry, fill_at_entry, snapshot["btc_price"], pnl, pnl)

                ctx = position.get("entry_context", {})

                # Record trade
                journal.record_trade(
                    entry_time=position["entry_time"],
                    direction=position["direction"],
                    entry_price=position["entry_price"],
                    size=position["size"],
                    assumption_name=position["assumption_name"],
                    exit_time=clock(),
                    exit_price=snapshot["btc_price"],
                    exit_reason=reason,
                    pnl=pnl,
                    source="mock" if hasattr(executor, '_equity') else "testnet",
                    entry_context=_json.dumps(ctx) if ctx else None,
                    regime_tag=ctx.get("regime_tag", "unknown"),
                    signal_correct=sig_correct,
                    slippage_bps=eq.get("slippage_bps", 0),
                    fill_delay_ms=fill_delay if fill_delay > 0 else 0,
                    realized_vs_expected_pnl=eq.get("realized_vs_expected_pnl", 1.0),
                    price_impact_bps=eq.get("price_impact_bps", 0),
                )
                position = None
                trades_completed += 1
                _print()
            else:
                _log("monitor \u2192 hold")
                _emit("monitor", action="hold")
        else:
            # ── Steps 2-6: decide → execute ──
            signal = core.decide(snapshot)

            if signal is None:
                _log("decide  \u2192 no signal")
                _emit("decide", signal=None)
            else:
                _log(f"decide  \u2192 {signal['direction']}")
                _emit("decide", signal=signal)

                # Step 3: declare
                assumptions = core.extract(signal)
                if assumptions:
                    aname = assumptions[0]["name"]
                    journal.ensure_assumption(aname, assumptions[0].get("description", ""))
                    _log(f"declare \u2192 \"{aname}\"")

                    # Step 4: check reliability from SQLite
                    stats = journal.get_assumption_stats(aname) or {"wins": 0, "total": 0}
                    reliability = (
                        stats["wins"] / stats["total"]
                        if stats["total"] > 0 else 0.5
                    )
                    _log(f"check   \u2192 reliability {reliability:.0%} "
                         f"({stats['wins']}/{stats['total']})")

                    # Step 5: size (Lean decides)
                    equity = executor.equity()
                    sizing = core.size(equity, reliability, stats["total"])
                    pos_size = sizing["position_size"]

                    _emit("size", position_size=pos_size, equity=equity,
                          reliability=reliability, sample_size=stats["total"])

                    if pos_size <= 0:
                        _log("size    \u2192 0 (no edge, skipping)")
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
                            ctx = core.build_context(snapshot)
                            position = {
                                "direction": signal["direction"],
                                "entry_price": result["price"],
                                "size": result["size"],
                                "leverage": leverage,
                                "stop_loss_pct": stop_loss_pct,
                                "entry_timestamp": snapshot["timestamp"],
                                "assumption_name": aname,
                                "entry_time": clock(),
                                "entry_context": ctx,
                                "mark_price_at_entry": snapshot["btc_price"],
                                "fill_price": result["price"],
                                "entry_ts_ms": int(time.time() * 1000),
                            }
                            _log(f"execute \u2192 {signal['direction']} "
                                 f"{result['size']:.6f} BTC @ "
                                 f"${result['price']:,.0f}")
                            _emit("execute_open", direction=signal["direction"],
                                  price=result["price"], size=result["size"],
                                  assumption=aname)
                        else:
                            _log(f"execute \u2192 FAILED: {result.get('error')}")
                    _print()

        if max_cycles == 0:
            time.sleep(5)

    final_stats = journal.get_assumption_stats("funding_rate_reverts_within_8h")
    return {
        "trades": trades_completed,
        "cycles": cycle - 1,
        "final_stats": final_stats,
    }


def run() -> None:
    """CLI entry point for the bundled example runner.

    This is not the Veritas product — it is a demo of a trading agent
    calling the verifier. Use `--live` to route observer/executor to
    Hyperliquid testnet instead of the fake in-process adapters.
    """
    live = "--live" in sys.argv
    core = VeritasCore()

    if live:
        import tomllib
        from python.observer import HyperliquidObserver
        from python.executor import HyperliquidExecutor

        cfg_path = Path("config.toml")
        if not cfg_path.exists():
            print("config.toml not found. Copy config.example.toml and fill in your private key.")
            sys.exit(1)
        with open(cfg_path, "rb") as f:
            cfg = tomllib.load(f)

        # New layout nests the adapter under [adapters.hyperliquid].
        # Fall back to the old top-level [hyperliquid] block for compatibility.
        hl_cfg = cfg.get("adapters", {}).get("hyperliquid") or cfg.get("hyperliquid", {})
        pk = hl_cfg.get("private_key", "")
        if not pk:
            print("Set adapters.hyperliquid.private_key in config.toml")
            sys.exit(1)

        coin = hl_cfg.get("coin") or cfg.get("strategy", {}).get("coin", "BTC")

        from eth_account import Account
        wallet = Account.from_key(pk)

        observer = HyperliquidObserver(coin, testnet=True, wallet_address=wallet.address)
        executor = HyperliquidExecutor(pk, coin, testnet=True)
    else:
        observer = FakeObserver()
        executor = FakeExecutor()

    try:
        run_loop(observer=observer, executor=executor, core=core, max_cycles=0)
    except KeyboardInterrupt:
        print("\nshutting down")


if __name__ == "__main__":
    run()
