"""Technical indicators used by the VWAP pullback strategy."""

from __future__ import annotations

import numpy as np
import pandas as pd


def session_vwap(df: pd.DataFrame) -> pd.Series:
    """Volume-weighted average price, reset at the start of each trading session (day).

    Expects a DatetimeIndex and columns: high, low, close, volume.
    """
    typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
    session_id = df.index.date
    pv = typical_price * df["volume"]
    cum_pv = pv.groupby(session_id).cumsum()
    cum_vol = df["volume"].groupby(session_id).cumsum()
    return cum_pv / cum_vol.replace(0, np.nan)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range (Wilder smoothing)."""
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def session_bar_index(df: pd.DataFrame) -> pd.Series:
    """0-based index of each bar within its trading session, for detecting session start/end."""
    session_id = df.index.date
    return pd.Series(np.arange(len(df)), index=df.index).groupby(session_id).cumcount()
