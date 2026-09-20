"""Prop-challenge Monte Carlo (Section 9.5): block-bootstrap the trade P&L
series and simulate sequential attempts against the firm's rules.

Because the strategy takes at most one trade per day (Section 3), each
entry in `daily_pnls` already represents exactly one trading day's dollar
outcome (0.0 for a day with no trade or a skipped trade), so there is no
separate day-grouping step — the block bootstrap operates directly on days.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _max_losing_streak(pnls: np.ndarray) -> int:
    streak = 0
    worst = 0
    for p in pnls:
        if p <= 0:
            streak += 1
            worst = max(worst, streak)
        else:
            streak = 0
    return worst


def _block_bootstrap_path(pnls: np.ndarray, length: int, block_len: tuple[int, int], rng: np.random.Generator) -> np.ndarray:
    n = len(pnls)
    chunks = []
    total = 0
    while total < length:
        bl = int(rng.integers(block_len[0], block_len[1] + 1))
        start = int(rng.integers(0, n))
        idx = (start + np.arange(bl)) % n
        chunks.append(pnls[idx])
        total += bl
    return np.concatenate(chunks)[:length]


def prop_monte_carlo(
    daily_pnls: np.ndarray,
    account_size: float,
    profit_target: float,
    trailing_dd: float,
    dd_type: str,
    daily_loss_limit: float,
    consistency_pct: float,
    min_days: int = 1,
    n_paths: int = 10000,
    block_len: tuple[int, int] = (5, 10),
    max_days: int = 252,
    seed: int | None = None,
) -> dict:
    """Simulate `n_paths` sequential-attempt equity paths.

    `dd_type` ("EOD" or "Intraday") is accepted for parity with the Pine
    inputs, but at one-trade-per-day granularity both measure the trailing
    drawdown once per day identically — see Section 7.3's own note that the
    intraday method is an approximation at bar granularity; here it is an
    approximation at day granularity for the same reason.
    """
    rng = np.random.default_rng(seed)
    pnls = np.asarray(daily_pnls, dtype=float)
    if len(pnls) == 0:
        raise ValueError("daily_pnls is empty")

    outcomes = []
    for _ in range(n_paths):
        path = _block_bootstrap_path(pnls, max_days, block_len, rng)

        equity = account_size
        peak = account_size
        best_day = -np.inf
        total_profit = 0.0
        passed = False
        breached = False
        days = 0
        equity_curve = [equity]

        for pnl in path:
            days += 1
            equity += pnl
            total_profit += pnl
            peak = max(peak, equity)
            equity_curve.append(equity)
            best_day = max(best_day, pnl)

            if peak - equity >= trailing_dd:
                breached = True
                break
            if pnl <= -daily_loss_limit:
                breached = True
                break
            if total_profit >= profit_target and days >= min_days:
                consistency_ok = total_profit > 0 and (best_day / total_profit * 100) <= consistency_pct
                if consistency_ok:
                    passed = True
                    break

        outcomes.append(
            {
                "passed": passed,
                "breached": breached,
                "days": days,
                "min_equity": min(equity_curve),
                "max_losing_streak": _max_losing_streak(path[:days]),
            }
        )

    df = pd.DataFrame(outcomes)
    return {
        "pass_rate": float(df["passed"].mean()),
        "breach_rate": float(df["breached"].mean()),
        "neither_rate": float((~df["passed"] & ~df["breached"]).mean()),
        "median_days_to_pass": float(df.loc[df["passed"], "days"].median()) if df["passed"].any() else float("nan"),
        "worst_case_losing_streak": int(df["max_losing_streak"].max()),
        "p5_equity_path_min": float(np.percentile(df["min_equity"], 5)),
        "n_paths": n_paths,
        "paths": df,
    }
