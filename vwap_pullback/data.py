"""Data loading for the VWAP pullback strategy.

Three sources are supported:
  - a local CSV/parquet file you already have (broker export, previously
    downloaded intraday bars, etc.)
  - yfinance (needs outbound internet access to Yahoo Finance; yfinance is an
    unofficial API and intraday history is limited to the last ~60 days for
    1m bars, ~730 days for 5m/15m/1h bars)
  - a synthetic generator (vwap_pullback.synthetic) for testing the mechanics
    of the strategy/backtester without any network access
"""

from __future__ import annotations

import pandas as pd

REQUIRED_COLUMNS = ["open", "high", "low", "close", "volume"]


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).lower().replace(" ", "_") for c in df.columns]
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Data is missing required columns: {missing}")
    df = df[REQUIRED_COLUMNS].astype(float)
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("Data must be indexed by a DatetimeIndex")
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df.dropna()


def load_csv(path: str, tz: str | None = None) -> pd.DataFrame:
    """Load OHLCV bars from CSV. Expects a timestamp column plus open/high/low/close/volume."""
    df = pd.read_csv(path)
    ts_col = next(
        (c for c in df.columns if c.lower() in ("timestamp", "datetime", "date", "time")),
        df.columns[0],
    )
    df[ts_col] = pd.to_datetime(df[ts_col])
    df = df.set_index(ts_col)
    if tz:
        df = df.tz_localize(tz) if df.index.tz is None else df.tz_convert(tz)
    return _normalize(df)


def load_yfinance(
    ticker: str,
    interval: str = "5m",
    period: str = "60d",
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """Download intraday bars via yfinance. Requires internet access and the yfinance package."""
    try:
        import yfinance as yf
    except ImportError as exc:
        raise ImportError(
            "yfinance is not installed. Run: pip install yfinance"
        ) from exc

    kwargs = {"interval": interval, "auto_adjust": False, "prepost": False}
    if start or end:
        kwargs["start"] = start
        kwargs["end"] = end
    else:
        kwargs["period"] = period

    df = yf.Ticker(ticker).history(**kwargs)
    if df.empty:
        raise ValueError(
            f"yfinance returned no data for {ticker!r} "
            f"(interval={interval!r}, period={period!r}). "
            "Intraday history is limited (~60d for 1m, ~730d for 5m/15m/1h)."
        )
    return _normalize(df)
