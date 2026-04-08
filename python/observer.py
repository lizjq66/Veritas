"""Hyperliquid API client — observe market state.

Pure I/O: fetches data, returns it as a dict. No decisions.
"""

import time


class HyperliquidObserver:
    """Fetches market data from Hyperliquid."""

    def __init__(self, coin: str = "BTC") -> None:
        self.coin = coin
        # SDK client will be initialized with config in v0.1 testnet phase
        self._client = None

    def snapshot(self) -> dict:
        """Return a MarketSnapshot dict for the Lean core."""
        if self._client is None:
            raise NotImplementedError(
                "Real Hyperliquid observer not yet connected. "
                "Use FakeObserver for local testing."
            )
        # TODO: call self._client for funding, price, OI
        raise NotImplementedError

    def equity(self) -> float:
        """Return current account equity in USD."""
        raise NotImplementedError

    def current_position(self) -> dict | None:
        """Return current open position, or None."""
        raise NotImplementedError


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
        base_ts = int(time.time())
        return [
            # Extreme negative funding → should trigger SHORT signal
            {"funding_rate": -0.0008, "btc_price": 68000.0,
             "timestamp": base_ts, "open_interest": 500_000_000.0},
            # Funding starts reverting
            {"funding_rate": -0.0004, "btc_price": 67800.0,
             "timestamp": base_ts + 3600, "open_interest": 490_000_000.0},
            # Funding near zero → assumption met
            {"funding_rate": -0.00005, "btc_price": 67900.0,
             "timestamp": base_ts + 7200, "open_interest": 495_000_000.0},
            # Calm market → no signal
            {"funding_rate": 0.0001, "btc_price": 68100.0,
             "timestamp": base_ts + 10800, "open_interest": 500_000_000.0},
            # Extreme positive funding → should trigger LONG signal
            {"funding_rate": 0.0012, "btc_price": 69000.0,
             "timestamp": base_ts + 14400, "open_interest": 520_000_000.0},
            # Funding drops → assumption met
            {"funding_rate": 0.00008, "btc_price": 69200.0,
             "timestamp": base_ts + 18000, "open_interest": 510_000_000.0},
        ]
