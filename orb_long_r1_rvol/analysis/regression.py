"""r1 -> later-session return regression, by year (Section 9.2).

This is the paper's own test (Gao, Han, Li, Zhou): does the direction
established early in the session (r1 = prior-close-to-10:00 return) predict
the return from 10:00 to the close? It is run on every RTH session in the
exported bar data, independent of whether a trade was taken that day, and is
the direct evidence for or against H1.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

ET = "America/New_York"


def _to_et(ts: pd.Series) -> pd.Series:
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize("UTC")
    return ts.dt.tz_convert(ET)


def build_daily_returns(bars: pd.DataFrame) -> pd.DataFrame:
    """One row per RTH session: r1, and the 10:00-to-close return."""
    if "close" not in bars.columns:
        raise ValueError("bars CSV has no 'close' column — re-export with OHLC columns included")

    df = bars.copy()
    df["time_et"] = _to_et(df["time"])
    df["date"] = df["time_et"].dt.date
    df["hhmm"] = df["time_et"].dt.hour * 100 + df["time_et"].dt.minute

    rows = []
    for date, g in df.groupby("date"):
        g = g.sort_values("time_et")
        rth = g[(g["hhmm"] >= 930) & (g["hhmm"] < 1600)]
        if rth.empty:
            continue
        r1_vals = rth["r1"].dropna() if "r1" in rth.columns else pd.Series(dtype=float)
        if r1_vals.empty:
            continue
        r1 = r1_vals.iloc[0]

        pre10 = rth[rth["hhmm"] < 1000]
        post10 = rth[rth["hhmm"] >= 1000]
        if pre10.empty or post10.empty:
            continue

        ref_close = pre10["close"].iloc[-1]
        day_close = post10["close"].iloc[-1]
        if ref_close == 0 or pd.isna(ref_close) or pd.isna(day_close):
            continue

        rows.append(
            {
                "date": date,
                "year": date.year,
                "r1": r1,
                "later_return": day_close / ref_close - 1,
            }
        )

    return pd.DataFrame(rows, columns=["date", "year", "r1", "later_return"])


def regression_by_year(daily: pd.DataFrame, min_obs: int = 5) -> pd.DataFrame:
    """OLS of later_return on r1, one regression per calendar year."""
    if daily.empty:
        return pd.DataFrame(columns=["year", "n", "slope", "intercept", "r2"])
    results = []
    for year, g in daily.groupby("year"):
        n = len(g)
        if n < min_obs:
            results.append({"year": year, "n": n, "slope": np.nan, "intercept": np.nan, "r2": np.nan})
            continue
        x = g["r1"].to_numpy()
        y = g["later_return"].to_numpy()
        slope, intercept = np.polyfit(x, y, 1)
        pred = slope * x + intercept
        ss_res = np.sum((y - pred) ** 2)
        ss_tot = np.sum((y - y.mean()) ** 2)
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan
        results.append({"year": year, "n": n, "slope": slope, "intercept": intercept, "r2": r2})
    return pd.DataFrame(results).sort_values("year").reset_index(drop=True)
