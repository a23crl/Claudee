"""Bucketed diagnostic tables (Section 5.6 / 9.3): expectancy by RVOL bucket,
by year, by day of week, and by exit type. Diagnostics only — never used to
change the frozen thresholds (Section 5.6's own warning).
"""

from __future__ import annotations

import pandas as pd

RVOL_EDGES = [0.0, 0.8, 1.2, 1.6, float("inf")]
RVOL_LABELS = ["<0.8", "0.8-1.2", "1.2-1.6", ">=1.6"]


def _executed(trades: pd.DataFrame) -> pd.DataFrame:
    return trades[~trades["skipped"]].dropna(subset=["net_r"]).copy()


def by_rvol_bucket(trades: pd.DataFrame) -> pd.DataFrame:
    df = _executed(trades)
    df["bucket"] = pd.cut(df["rvol"], RVOL_EDGES, labels=RVOL_LABELS, right=False)
    out = df.groupby("bucket", observed=False)["net_r"].agg(trades="count", avg_r="mean").reset_index()
    return out


def by_year(trades: pd.DataFrame) -> pd.DataFrame:
    df = _executed(trades)
    df["year"] = pd.to_datetime(df["exit_time"]).dt.year
    return df.groupby("year")["net_r"].agg(trades="count", total_r="sum").reset_index()


def by_day_of_week(trades: pd.DataFrame) -> pd.DataFrame:
    df = _executed(trades)
    df["dow"] = pd.to_datetime(df["exit_time"]).dt.day_name()
    return df.groupby("dow")["net_r"].agg(trades="count", avg_r="mean").reset_index()


def by_exit_type(trades: pd.DataFrame) -> pd.DataFrame:
    df = _executed(trades)
    return df.groupby("exit_type")["net_r"].agg(trades="count", avg_r="mean").reset_index()


def max_year_share_of_total_r(trades: pd.DataFrame) -> float:
    """Section 8.7: no single year may contribute more than 40% of total R."""
    yearly = by_year(trades)
    total = yearly["total_r"].sum()
    if total == 0 or len(yearly) == 0:
        return float("nan")
    return float((yearly["total_r"].abs().max()) / abs(total))


def share_of_years_net_positive(trades: pd.DataFrame) -> float:
    """Section 8.7: at least 60% of years with trades must be net positive."""
    yearly = by_year(trades)
    if len(yearly) == 0:
        return float("nan")
    return float((yearly["total_r"] > 0).mean())
