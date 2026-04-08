"""Hyperliquid order placement — execute trades.

Pure I/O: places orders, returns results. No decisions.
"""


class HyperliquidExecutor:
    """Places orders on Hyperliquid."""

    def __init__(self, coin: str = "BTC") -> None:
        self.coin = coin
        self._client = None

    def open_position(self, direction: str, size_usd: float) -> dict:
        raise NotImplementedError(
            "Real executor not yet connected. Use FakeExecutor for testing."
        )

    def close_position(self) -> dict:
        raise NotImplementedError

    def current_position(self) -> dict | None:
        raise NotImplementedError

    def equity(self) -> float:
        raise NotImplementedError


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
