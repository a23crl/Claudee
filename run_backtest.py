#!/usr/bin/env python3
"""CLI: run the VWAP pullback backtest end-to-end and write a report.

Examples:
    # Real data via yfinance (needs internet; run on your own machine)
    python run_backtest.py --ticker SPY --interval 5m --period 60d

    # Your own CSV of intraday OHLCV bars
    python run_backtest.py --csv path/to/bars.csv

    # No data source at hand: synthetic data to sanity-check the mechanics
    python run_backtest.py --synthetic trending --days 250
    python run_backtest.py --synthetic random_walk --days 250   # edge sanity check
"""

from __future__ import annotations

import argparse

from vwap_pullback import data, synthetic
from vwap_pullback.backtest import BacktestParams, run_backtest
from vwap_pullback.metrics import compute_metrics, format_report
from vwap_pullback.report import save_all
from vwap_pullback.strategy import VWAPPullbackParams, generate_signals


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)

    source = p.add_argument_group("data source (pick one)")
    source.add_argument("--ticker", type=str, help="Ticker to download via yfinance")
    source.add_argument("--interval", type=str, default="5m", help="Bar interval for yfinance (default: 5m)")
    source.add_argument("--period", type=str, default="60d", help="yfinance lookback period (default: 60d)")
    source.add_argument("--start", type=str, default=None, help="yfinance start date (YYYY-MM-DD)")
    source.add_argument("--end", type=str, default=None, help="yfinance end date (YYYY-MM-DD)")
    source.add_argument("--csv", type=str, help="Path to a CSV of OHLCV bars")
    source.add_argument(
        "--synthetic", choices=["trending", "random_walk"], help="Generate synthetic data instead of real data"
    )
    source.add_argument("--days", type=int, default=250, help="Number of sessions for --synthetic (default: 250)")
    source.add_argument("--seed", type=int, default=7, help="Random seed for --synthetic (default: 7)")

    strat = p.add_argument_group("strategy parameters")
    strat.add_argument("--atr-period", type=int, default=14)
    strat.add_argument("--min-extension-atr", type=float, default=1.0)
    strat.add_argument("--min-trend-bars", type=int, default=3)
    strat.add_argument("--pullback-atr-mult", type=float, default=0.35)
    strat.add_argument("--no-momentum-break", action="store_true", help="Disable the momentum-break confirmation")
    strat.add_argument("--stop-lookback", type=int, default=5)
    strat.add_argument("--stop-buffer-atr", type=float, default=0.1)
    strat.add_argument("--reward-r", type=float, default=2.0)

    bt = p.add_argument_group("backtest parameters")
    bt.add_argument("--cash", type=float, default=100_000.0)
    bt.add_argument("--risk-pct", type=float, default=0.0075)
    bt.add_argument("--commission-bps", type=float, default=1.0)
    bt.add_argument("--slippage-bps", type=float, default=1.0)
    bt.add_argument("--max-exposure-pct", type=float, default=1.0)
    bt.add_argument("--no-short", action="store_true", help="Disable short trades")

    p.add_argument("--out-dir", type=str, default="output", help="Directory for report files (default: output)")
    return p


def load_data(args: argparse.Namespace):
    if args.csv:
        return data.load_csv(args.csv)
    if args.ticker:
        return data.load_yfinance(args.ticker, interval=args.interval, period=args.period, start=args.start, end=args.end)
    if args.synthetic:
        return synthetic.generate(n_days=args.days, regime=args.synthetic, seed=args.seed)
    raise SystemExit("Provide one data source: --ticker, --csv, or --synthetic")


def main() -> None:
    args = build_arg_parser().parse_args()
    df = load_data(args)
    print(f"Loaded {len(df)} bars from {df.index[0]} to {df.index[-1]}")

    strat_params = VWAPPullbackParams(
        atr_period=args.atr_period,
        min_extension_atr=args.min_extension_atr,
        min_trend_bars=args.min_trend_bars,
        pullback_atr_mult=args.pullback_atr_mult,
        require_momentum_break=not args.no_momentum_break,
        stop_lookback=args.stop_lookback,
        stop_buffer_atr=args.stop_buffer_atr,
        reward_r=args.reward_r,
    )
    signals_df = generate_signals(df, strat_params)
    n_signals = signals_df["signal"].notna().sum()
    print(f"Generated {n_signals} raw signals")

    bt_params = BacktestParams(
        initial_cash=args.cash,
        risk_pct=args.risk_pct,
        reward_r=args.reward_r,
        commission_bps=args.commission_bps,
        slippage_bps=args.slippage_bps,
        max_gross_exposure_pct=args.max_exposure_pct,
        allow_short=not args.no_short,
    )
    trades, equity_curve = run_backtest(signals_df, bt_params)

    metrics = compute_metrics(trades, equity_curve, bt_params.initial_cash)
    print(format_report(metrics))

    save_all(signals_df, trades, equity_curve, args.out_dir)
    print(f"\nSaved equity_curve.png, drawdown.png, price_trades.png, trades.csv -> {args.out_dir}/")


if __name__ == "__main__":
    main()
