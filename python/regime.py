from __future__ import annotations

"""Market regime classifier — first-pass, hand-coded.

Classifier v0.1 (WILL BE REVISITED):
    price_change_24h > +2%  → bull
    price_change_24h < -2%  → bear
    otherwise               → choppy

This is deliberately crude. It uses only the 24h price change from
the Hyperliquid API (prevDayPx vs markPx). A better classifier would
incorporate volatility, volume profile, and possibly LLM analysis.
The architecture stores the raw context alongside the tag so future
classifiers can retroactively re-tag historical trials.
"""

VALID_REGIMES = ("bull", "bear", "choppy", "unknown")


def classify_regime(price_change_24h: float) -> str:
    """Classify current market regime from 24h price change.

    Args:
        price_change_24h: (current - prev_day) / prev_day, e.g. 0.03 = +3%
    """
    if price_change_24h > 0.02:
        return "bull"
    elif price_change_24h < -0.02:
        return "bear"
    else:
        return "choppy"


def build_entry_context(snapshot: dict, prev_day_price: float | None = None) -> dict:
    """Build the rich context dict to store with each trial.

    8 context features, all cheaply observable from existing API data:
      1. funding_rate     — current hourly funding rate
      2. asset_price      — mark price at signal time
      3. open_interest    — total OI (base units)
      4. volume_24h       — 24h notional volume (USD)
      5. premium          — perp premium over oracle price
      6. price_change_24h — 24h return as decimal
      7. spread_bps       — bid-ask spread in basis points
      8. regime_tag       — bull/bear/choppy/unknown
    """
    price = snapshot.get("btc_price", 0)
    prev = prev_day_price or snapshot.get("prev_day_price")

    if prev and prev > 0:
        price_change_24h = (price - prev) / prev
    else:
        price_change_24h = 0.0

    return {
        "funding_rate": snapshot.get("funding_rate", 0),
        "asset_price": price,
        "open_interest": snapshot.get("open_interest", 0),
        "volume_24h": snapshot.get("volume_24h", 0),
        "premium": snapshot.get("premium", 0),
        "price_change_24h": round(price_change_24h, 6),
        "spread_bps": snapshot.get("spread_bps", 0),
        "regime_tag": classify_regime(price_change_24h),
    }
