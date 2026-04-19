from __future__ import annotations

"""Executor adapter — Hyperliquid order placement (example).

This is an example adapter, not part of the Veritas verifier product.
Executors are downstream of Veritas — they receive a notional that has
already cleared all three gates and translate it into a venue-specific
order. Swap it for a different venue by writing a new class with the
same surface.

Pure I/O: places orders, returns results. No decisions.
"""

import requests
from eth_account import Account

from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants


_TESTNET_URL = "https://api.hyperliquid-testnet.xyz"
_INFO_URL = _TESTNET_URL + "/info"


class HyperliquidExecutor:
    """Places orders on Hyperliquid testnet."""

    def __init__(self, private_key: str, coin: str = "BTC", *,
                 testnet: bool = True) -> None:
        self.coin = coin
        self._wallet = Account.from_key(private_key)
        base_url = constants.TESTNET_API_URL if testnet else constants.MAINNET_API_URL
        self._exchange = Exchange(self._wallet, base_url)
        self._info_url = _INFO_URL if testnet else "https://api.hyperliquid.xyz/info"

    def _post_info(self, payload: dict) -> dict | list:
        resp = requests.post(self._info_url, json=payload, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def open_position(self, direction: str, size_usd: float, price: float,
                      leverage: float, _stop_loss_pct: float,
                      _assumption_name: str, _entry_timestamp: int) -> dict:
        """Open a position. size_usd is notional; converted to base units."""
        is_buy = direction == "LONG"
        sz = round(size_usd / price, 5)  # BTC has 5 sz decimals

        try:
            self._exchange.update_leverage(int(leverage) or 1, self.coin)
        except Exception:
            pass  # leverage may already be set

        result = self._exchange.market_open(self.coin, is_buy, sz)
        status = result.get("status", "")
        if status == "ok":
            # Extract fill price from response
            fills = result.get("response", {}).get("data", {}).get("statuses", [])
            fill_px = price  # fallback
            for f in fills:
                if "filled" in f:
                    fill_px = float(f["filled"]["avgPx"])
                    sz = float(f["filled"]["totalSz"])
                    break
            return {"ok": True, "price": fill_px, "size": sz}
        else:
            return {"ok": False, "error": str(result)}

    def close_position(self, exit_price: float) -> dict:
        """Close current position in self.coin."""
        result = self._exchange.market_close(self.coin)
        if result is None:
            return {"ok": False, "error": "no position to close"}
        status = result.get("status", "")
        if status == "ok":
            fills = result.get("response", {}).get("data", {}).get("statuses", [])
            fill_px = exit_price
            for f in fills:
                if "filled" in f:
                    fill_px = float(f["filled"]["avgPx"])
                    break
            return {"ok": True, "price": fill_px}
        else:
            return {"ok": False, "error": str(result)}

    def current_position(self) -> dict | None:
        """Return current position for self.coin, or None."""
        state = self._post_info({
            "type": "clearinghouseState",
            "user": self._wallet.address,
        })
        for pos in state.get("assetPositions", []):
            p = pos.get("position", {})
            if p.get("coin") == self.coin and float(p.get("szi", "0")) != 0:
                szi = float(p["szi"])
                return {
                    "direction": "LONG" if szi > 0 else "SHORT",
                    "entry_price": float(p["entryPx"]),
                    "size": abs(szi),
                }
        return None

    def equity(self) -> float:
        """Return account equity in USD."""
        state = self._post_info({
            "type": "clearinghouseState",
            "user": self._wallet.address,
        })
        return float(state["marginSummary"]["accountValue"])


class FakeExecutor:
    """Simulated executor for local testing."""

    def __init__(self, initial_equity: float = 10000.0) -> None:
        self._equity = initial_equity
        self._position: dict | None = None

    def open_position(self, direction: str, size_usd: float, price: float,
                      leverage: float, stop_loss_pct: float,
                      assumption_name: str, entry_timestamp: int) -> dict:
        self._position = {
            "direction": direction,
            "entry_price": price,
            "size": size_usd / price,
            "leverage": leverage,
            "stop_loss_pct": stop_loss_pct,
            "entry_timestamp": entry_timestamp,
            "assumption_name": assumption_name,
        }
        return {"ok": True, "price": price, "size": self._position["size"]}

    def close_position(self, exit_price: float) -> dict:
        if self._position is None:
            return {"ok": False, "error": "no position"}
        pos = self._position
        if pos["direction"] == "LONG":
            pnl_pct = (exit_price - pos["entry_price"]) / pos["entry_price"] * 100
        else:
            pnl_pct = (pos["entry_price"] - exit_price) / pos["entry_price"] * 100
        self._position = None
        return {"ok": True, "price": exit_price, "pnl_pct": round(pnl_pct, 4)}

    def current_position(self) -> dict | None:
        return self._position

    def equity(self) -> float:
        return self._equity
