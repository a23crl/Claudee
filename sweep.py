#!/usr/bin/env python3
"""Parameter sensitivity sweep: run the backtest across a grid of strategy
parameters on the same data and report Sharpe/return/trade-count for each
combination.

This is a robustness check, not a way to find the "best" parameters: a
strategy whose Sharpe swings from strongly positive to strongly negative
across small parameter changes is likely fit to noise and should not be
trusted with real money regardless of how good its best cell looks.

Example:
    python sweep.py --synthetic trending --days 250
    python sweep.py --csv path/to/bars.csv
"""

from __future__ import annotations

import argparse
import itertools

import pandas as pd

from vwap_pullback import data, synthetic
from vwap_pullback.backtest import BacktestParams, run_backtest
from vwap_pullback.metrics import compute_metrics
from vwap_pullback.strategy import VWAPPullbackParams, generate_signals

MIN_EXTENSION_GRID = [0.75, 1.0, 1.5]
PULLBACK_MULT_GRID = [0.25, 0.35, 0.5]
REWARD_R_GRID = [1.5, 2.0, 3.0]


def load_data(args: argparse.Namespace) -> pd.DataFrame:
    if args.csv:
        return data.load_csv(args.csv)
    if args.ticker:
        return data.load_yfinance(args.ticker, interval=args.interval, period=args.period)
    return synthetic.generate(n_days=args.days, regime=args.synthetic, seed=args.seed)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ticker", type=str)
    p.add_argument("--interval", type=str, default="5m")
    p.add_argument("--period", type=str, default="60d")
    p.add_argument("--csv", type=str)
    p.add_argument("--synthetic", choices=["trending", "random_walk"], default="trending")
    p.add_argument("--days", type=int, default=250)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--cash", type=float, default=100_000.0)
    p.add_argument("--risk-pct", type=float, default=0.0075)
    args = p.parse_args()

    df = load_data(args)
    print(f"Loaded {len(df)} bars from {df.index[0]} to {df.index[-1]}\n")

    rows = []
    for min_ext, pullback_mult, reward_r in itertools.product(
        MIN_EXTENSION_GRID, PULLBACK_MULT_GRID, REWARD_R_GRID
    ):
        strat_params = VWAPPullbackParams(
            min_extension_atr=min_ext, pullback_atr_mult=pullback_mult, reward_r=reward_r
        )
        signals_df = generate_signals(df, strat_params)
        bt_params = BacktestParams(initial_cash=args.cash, risk_pct=args.risk_pct, reward_r=reward_r)
        trades, equity = run_backtest(signals_df, bt_params)
        m = compute_metrics(trades, equity, bt_params.initial_cash)
        rows.append(
            {
                "min_extension_atr": min_ext,
                "pullback_atr_mult": pullback_mult,
                "reward_r": reward_r,
                "num_trades": m["num_trades"],
                "total_return_pct": round(m["total_return_pct"], 2),
                "sharpe": round(m["sharpe"], 2) if pd.notna(m["sharpe"]) else float("nan"),
                "max_drawdown_pct": round(m["max_drawdown_pct"], 2),
                "win_rate_pct": round(m["win_rate_pct"], 1) if pd.notna(m["win_rate_pct"]) else float("nan"),
            }
        )

    result = pd.DataFrame(rows).sort_values("sharpe", ascending=False)
    pd.set_option("display.width", 140)
    print(result.to_string(index=False))

    sharpe_vals = result["sharpe"].dropna()
    if len(sharpe_vals):
        frac_positive = (sharpe_vals > 0).mean()
        print(f"\n{frac_positive:.0%} of parameter combinations had a positive Sharpe.")
        print(f"Sharpe range across the grid: {sharpe_vals.min():.2f} to {sharpe_vals.max():.2f}")


if __name__ == "__main__":
    main()
