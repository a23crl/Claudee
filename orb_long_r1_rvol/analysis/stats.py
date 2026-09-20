"""Recompute the same per-sample statistics the Pine table shows (Section 5.6),
independently of Pine, so the two can be cross-checked (Section 9.1).
"""

from __future__ import annotations

import math

import pandas as pd


def compute_stats(trades: pd.DataFrame) -> dict:
    """Trades, win rate, avg R, payoff ratio, profit factor, max losing
    streak, max drawdown (R), average ticks, skipped count — for whatever
    subset of `trades` is passed in (already filtered by sample)."""
    skipped = int(trades["skipped"].sum()) if len(trades) else 0
    executed = trades[~trades["skipped"]].copy()
    executed = executed.dropna(subset=["net_r"]).sort_values("exit_time")
    n = len(executed)

    if n == 0:
        return {
            "trades": 0,
            "win_rate": float("nan"),
            "avg_r": float("nan"),
            "payoff_ratio": float("nan"),
            "profit_factor": float("nan"),
            "max_losing_streak": 0,
            "max_drawdown_r": 0.0,
            "skipped": skipped,
        }

    wins = executed[executed["net_r"] > 0]
    losses = executed[executed["net_r"] <= 0]

    win_rate = len(wins) / n * 100
    avg_r = executed["net_r"].mean()
    avg_win = wins["net_r"].mean() if len(wins) else float("nan")
    avg_loss = -losses["net_r"].mean() if len(losses) else float("nan")
    payoff_ratio = avg_win / avg_loss if (not math.isnan(avg_loss) and avg_loss != 0) else float("nan")

    gross_win = wins["net_r"].sum()
    gross_loss = -losses["net_r"].sum()
    profit_factor = gross_win / gross_loss if gross_loss > 0 else float("nan")

    streak = 0
    max_streak = 0
    for r in executed["net_r"]:
        if r <= 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0

    equity = executed["net_r"].cumsum()
    max_dd = float((equity.cummax() - equity).max())

    return {
        "trades": n,
        "win_rate": win_rate,
        "avg_r": avg_r,
        "payoff_ratio": payoff_ratio,
        "profit_factor": profit_factor,
        "max_losing_streak": max_streak,
        "max_drawdown_r": max_dd,
        "skipped": skipped,
    }


def cross_check(recomputed: dict, pine_reported: dict, rtol: float = 1e-2) -> list[str]:
    """Compare this module's numbers against the ones read off the Pine
    table. Per Section 9.1 these must match to within rounding — a mismatch
    means the Pine logic (or this recompute) has a bug, not a real finding."""
    mismatches = []
    for key, expected in pine_reported.items():
        if key not in recomputed:
            mismatches.append(f"{key}: not present in recomputed stats")
            continue
        actual = recomputed[key]
        if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
            if math.isnan(expected) and math.isnan(actual):
                continue
            if not math.isclose(expected, actual, rel_tol=rtol, abs_tol=1e-6):
                mismatches.append(f"{key}: pine={expected} vs recomputed={actual}")
        elif expected != actual:
            mismatches.append(f"{key}: pine={expected} vs recomputed={actual}")
    return mismatches
