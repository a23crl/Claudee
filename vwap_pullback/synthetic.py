"""Synthetic intraday OHLCV data for exercising the strategy/backtester without network access.

This is NOT a substitute for real market data. It exists so the mechanics
(VWAP calc, signal logic, fills, position sizing, metrics) can be validated
end-to-end offline. Two regimes are provided:

  - "trending": bars built from a drift + mean-reversion-to-drift process,
    which manufactures the kind of trend/pullback structure the strategy
    looks for. Used to sanity-check that signals fire and trades make sense.
  - "random_walk": pure geometric Brownian motion with no exploitable
    structure. A strategy that still shows a strong positive edge here
    likely has a lookahead-bias or accounting bug, not real alpha.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _session_timestamps(n_days: int, bars_per_day: int, freq_minutes: int, start_date: str) -> pd.DatetimeIndex:
    sessions = pd.bdate_range(start=start_date, periods=n_days, tz="America/New_York")
    all_ts = []
    for day in sessions:
        session_open = day.replace(hour=9, minute=30)
        ts = pd.date_range(session_open, periods=bars_per_day, freq=f"{freq_minutes}min")
        all_ts.append(ts)
    return pd.DatetimeIndex(np.concatenate(all_ts))


def generate(
    n_days: int = 120,
    freq_minutes: int = 5,
    bars_per_day: int = 78,  # 6.5h session / 5min bars
    start_price: float = 100.0,
    regime: str = "trending",
    seed: int = 7,
    start_date: str = "2024-01-02",
) -> pd.DataFrame:
    """Generate synthetic intraday OHLCV bars.

    regime: "trending" (drift + pullback structure) or "random_walk" (pure noise).
    """
    if regime not in ("trending", "random_walk"):
        raise ValueError("regime must be 'trending' or 'random_walk'")

    rng = np.random.default_rng(seed)
    index = _session_timestamps(n_days, bars_per_day, freq_minutes, start_date)
    n = len(index)

    bar_vol = 0.0009  # per-bar noise stdev (~1.4% daily vol at 78 bars/day)
    closes = np.empty(n)
    price = start_price

    if regime == "random_walk":
        rets = rng.normal(0, bar_vol, n)
        closes = start_price * np.exp(np.cumsum(rets))
    else:
        # Each session gets a random drift regime (up/down/flat) plus
        # mean-reverting noise around a session VWAP-like anchor, which
        # produces trend-then-pullback-to-anchor structure across the day.
        drift_per_bar = 0.00035
        pullback_strength = 0.35
        pos = 0
        for day_start in range(0, n, bars_per_day):
            day_len = min(bars_per_day, n - day_start)
            session_bias = rng.choice([1.0, -1.0, 0.0], p=[0.4, 0.4, 0.2])
            anchor = price
            for i in range(day_len):
                noise = rng.normal(0, bar_vol)
                reversion = pullback_strength * (anchor - price) / max(price, 1e-6)
                price = price * (1 + session_bias * drift_per_bar + noise) + reversion * price * 0.02
                anchor = anchor * (1 + session_bias * drift_per_bar * 0.6)
                closes[pos] = price
                pos += 1

    opens = np.empty(n)
    opens[0] = start_price
    opens[1:] = closes[:-1]

    intrabar_range = np.abs(rng.normal(0, bar_vol * 0.8, n)) * closes
    highs = np.maximum(opens, closes) + intrabar_range
    lows = np.minimum(opens, closes) - intrabar_range
    lows = np.maximum(lows, 0.01)

    base_volume = 50_000
    volumes = np.abs(rng.normal(base_volume, base_volume * 0.3, n)).astype(int) + 1

    df = pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        },
        index=index,
    )
    df.index.name = "timestamp"
    return df
