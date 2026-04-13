from __future__ import annotations

"""Hyperliquid API client — observe market state.

Pure I/O: fetches data, returns it as a dict. No decisions.
"""

import time

import requests


_TESTNET_URL = "https://api.hyperliquid-testnet.xyz/info"
_MAINNET_URL = "https://api.hyperliquid.xyz/info"


class HyperliquidObserver:
    """Fetches market data from Hyperliquid via REST API."""

    def __init__(self, coin: str = "BTC", *, testnet: bool = True,
                 wallet_address: str = "") -> None:
        self.coin = coin
        self._url = _TESTNET_URL if testnet else _MAINNET_URL
        self._wallet = wallet_address
        # Resolve coin index in the universe on first call
        self._coin_index: int | None = None

    def _post(self, payload: dict) -> dict | list:
        resp = requests.post(self._url, json=payload, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _resolve_index(self, meta: dict) -> int:
        """Find the index of self.coin in meta['universe']."""
        if self._coin_index is not None:
            return self._coin_index
        for i, asset in enumerate(meta["universe"]):
            if asset.get("name") == self.coin:
                self._coin_index = i
                return i
        raise ValueError(f"{self.coin} not found in Hyperliquid universe")

    def snapshot(self) -> dict:
        """Return current market state matching veritas-core's schema:
        {"funding_rate": float, "btc_price": float,
         "timestamp": int, "open_interest": float}
        """
        data = self._post({"type": "metaAndAssetCtxs"})
        meta, ctxs = data[0], data[1]
        idx = self._resolve_index(meta)
        ctx = ctxs[idx]

        mark = float(ctx["markPx"])
        prev = float(ctx.get("prevDayPx", mark))
        bid_impact = float(ctx.get("impactPxs", [mark, mark])[0])
        ask_impact = float(ctx.get("impactPxs", [mark, mark])[1])
        mid = (bid_impact + ask_impact) / 2 if (bid_impact + ask_impact) > 0 else mark
        spread_bps = (ask_impact - bid_impact) / mid * 10000 if mid > 0 else 0

        return {
            "funding_rate": float(ctx["funding"]),
            "btc_price": mark,
            "timestamp": int(time.time()),
            "open_interest": float(ctx["openInterest"]),
            "volume_24h": float(ctx.get("dayNtlVlm", 0)),
            "premium": float(ctx.get("premium", 0)),
            "prev_day_price": prev,
            "spread_bps": round(spread_bps, 2),
        }

    def equity(self) -> float:
        """Return current account equity in USD."""
        if not self._wallet:
            raise ValueError("wallet_address required for equity()")
        state = self._post({
            "type": "clearinghouseState",
            "user": self._wallet,
        })
        return float(state["marginSummary"]["accountValue"])

    def current_position(self) -> dict | None:
        """Return current open position for self.coin, or None."""
        if not self._wallet:
            raise ValueError("wallet_address required for current_position()")
        state = self._post({
            "type": "clearinghouseState",
            "user": self._wallet,
        })
        for pos in state.get("assetPositions", []):
            p = pos.get("position", {})
            if p.get("coin") == self.coin and float(p.get("szi", "0")) != 0:
                szi = float(p["szi"])
                return {
                    "direction": "LONG" if szi > 0 else "SHORT",
                    "entry_price": float(p["entryPx"]),
                    "size": abs(szi),
                    "unrealized_pnl": float(p.get("unrealizedPnl", "0")),
                }
        return None


class FakeObserver:
    """Simulated observer for local testing without Hyperliquid."""

    def __init__(self, scenarios: list[dict] | None = None) -> None:
        self._scenarios = scenarios or self._default_scenarios()
        self._index = 0

    def snapshot(self) -> dict:
        if self._index >= len(self._scenarios):
            self._index = 0
        snap = self._scenarios[self._index]
        self._index += 1
        return snap

    def equity(self) -> float:
        return 10000.0

    def current_position(self) -> dict | None:
        return None

    @staticmethod
    def _default_scenarios() -> list[dict]:
        """A simple funding spike → reversion cycle."""
        base_ts = 1700000000  # fixed epoch for deterministic replay
        defaults = {"volume_24h": 5_000_000.0, "premium": 0.001,
                     "prev_day_price": 68000.0, "spread_bps": 15.0}
        return [
            {"funding_rate": -0.0008, "btc_price": 68000.0,
             "timestamp": base_ts, "open_interest": 500_000_000.0, **defaults},
            {"funding_rate": -0.0004, "btc_price": 67800.0,
             "timestamp": base_ts + 3600, "open_interest": 490_000_000.0, **defaults},
            {"funding_rate": -0.00005, "btc_price": 67900.0,
             "timestamp": base_ts + 7200, "open_interest": 495_000_000.0, **defaults},
            {"funding_rate": 0.0001, "btc_price": 68100.0,
             "timestamp": base_ts + 10800, "open_interest": 500_000_000.0, **defaults},
            {"funding_rate": 0.0012, "btc_price": 69000.0,
             "timestamp": base_ts + 14400, "open_interest": 520_000_000.0, **defaults},
            {"funding_rate": 0.00008, "btc_price": 69200.0,
             "timestamp": base_ts + 18000, "open_interest": 510_000_000.0, **defaults},
        ]
