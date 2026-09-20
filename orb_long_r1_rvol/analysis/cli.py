"""CLI: run the Section 9 validation pipeline over a Pine-exported CSV.

Steps (Section 9):
  1. Load trades, split by sampleId, recompute stats (cross-check vs. Pine).
  2. r1 -> later-session return regression by year.
  3. Bucketed tables: RVOL bucket, year, day of week, exit type.
  4. B3 randomized-direction baseline + permutation test on the primary.
  5. Prop-challenge Monte Carlo.
  6. Risk-per-trade sweep.
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd

from . import baseline, buckets, io, montecarlo, regression, risk_sweep, stats

SAMPLE_NAMES = {"design": 0, "validation": 1, "holdout": 2}


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--csv", required=True, help="Path to TradingView's exported chart data CSV")
    p.add_argument("--include-holdout", action="store_true",
                    help="Include the holdout sample in the report. Only pass this once, after unlocking the "
                         "indicator's holdout switch and logging the frozen candidate (Section 7.2).")

    prop = p.add_argument_group("prop-firm rules (must match the indicator's Risk / Prop Firm inputs)")
    prop.add_argument("--account-size", type=float, default=50000.0)
    prop.add_argument("--profit-target", type=float, default=3000.0)
    prop.add_argument("--trailing-dd", type=float, default=2000.0)
    prop.add_argument("--dd-type", choices=["EOD", "Intraday"], default="EOD")
    prop.add_argument("--daily-loss-limit", type=float, default=1000.0)
    prop.add_argument("--consistency-pct", type=float, default=30.0)
    prop.add_argument("--risk-per-trade", type=float, default=200.0,
                       help="Risk $ per trade used for the base Monte Carlo run (Section 9.5)")
    prop.add_argument("--n-paths", type=int, default=10000)
    prop.add_argument("--seed", type=int, default=7)

    return p


def _print_header(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)

    bars = io.load_bars(args.csv)
    trades = io.extract_trades(bars)
    if len(trades) == 0:
        sys.exit("No trades found in the exported CSV — check that the data-window plots were enabled on export.")

    samples = io.split_by_sample(trades)
    visible_samples = {"design", "validation"} | ({"holdout"} if args.include_holdout else set())

    # --- 1. per-sample stats -------------------------------------------------
    _print_header("1. Per-sample statistics (cross-check these against the Pine table)")
    for name in ["design", "validation", "holdout"]:
        if name not in visible_samples:
            print(f"{name:>10}: HOLDOUT LOCKED (pass --include-holdout after unlocking in Pine)")
            continue
        s = stats.compute_stats(samples[name])
        print(f"{name:>10}: {s}")

    visible_trades = pd.concat([samples[n] for n in visible_samples], ignore_index=True) if visible_samples else trades.iloc[0:0]

    # --- 2. r1 continuation regression ---------------------------------------
    _print_header("2. r1 -> 10:00-to-close return regression, by year (H1 test)")
    if "close" in bars.columns:
        daily = regression.build_daily_returns(bars)
        if daily.empty:
            print("No RTH sessions with both an r1 value and pre/post-10:00 closes were found in this export.")
        else:
            reg = regression.regression_by_year(daily)
            print(reg.to_string(index=False))
    else:
        print("Skipped: exported CSV has no 'close' column.")

    # --- 3. bucketed diagnostics ----------------------------------------------
    _print_header("3. Bucketed diagnostics (design + validation)")
    design_and_valid = pd.concat([samples["design"], samples["validation"]], ignore_index=True)
    print("\nBy RVOL bucket (diagnostic only — never used to retune the threshold):")
    print(buckets.by_rvol_bucket(design_and_valid).to_string(index=False))
    print("\nBy year:")
    print(buckets.by_year(design_and_valid).to_string(index=False))
    print(f"Max single-year share of total R: {buckets.max_year_share_of_total_r(design_and_valid):.1%} (must be <= 40%)")
    print(f"Share of years net positive: {buckets.share_of_years_net_positive(design_and_valid):.1%} (must be >= 60%)")
    print("\nBy day of week:")
    print(buckets.by_day_of_week(design_and_valid).to_string(index=False))
    print("\nBy exit type:")
    print(buckets.by_exit_type(design_and_valid).to_string(index=False))

    # --- 4. B3 baseline + permutation test ------------------------------------
    _print_header("4. B3 randomized-direction baseline + permutation test")
    b3 = baseline.randomize_direction_baseline(design_and_valid, seed=args.seed)
    print(f"B3 mean R (randomized direction): {b3['net_r_random_direction'].mean():.4f} (n={len(b3)})")
    executed = design_and_valid[~design_and_valid["skipped"]].dropna(subset=["net_r"])
    perm = baseline.permutation_test(executed["net_r"], n_iter=10000, seed=args.seed)
    print(f"Primary permutation test: {perm}")
    print(f"t-stat of mean R (validation-only, for the multiple-testing haircut): "
          f"{baseline.t_stat(samples['validation']['net_r']):.3f}")

    # --- 5. prop Monte Carlo ----------------------------------------------------
    _print_header("5. Prop-challenge Monte Carlo (block bootstrap, %d paths)" % args.n_paths)
    daily_pnls = executed["net_r"].to_numpy() * args.risk_per_trade
    mc = montecarlo.prop_monte_carlo(
        daily_pnls,
        account_size=args.account_size,
        profit_target=args.profit_target,
        trailing_dd=args.trailing_dd,
        dd_type=args.dd_type,
        daily_loss_limit=args.daily_loss_limit,
        consistency_pct=args.consistency_pct,
        n_paths=args.n_paths,
        seed=args.seed,
    )
    for k, v in mc.items():
        if k != "paths":
            print(f"  {k}: {v}")

    # --- 6. risk-per-trade sweep -------------------------------------------------
    _print_header("6. Risk-per-trade sweep (fixed grid: 5% / 10% / 15% / 20% of drawdown buffer)")
    sweep = risk_sweep.risk_per_trade_sweep(
        executed["net_r"].to_numpy(),
        account_size=args.account_size,
        profit_target=args.profit_target,
        trailing_dd=args.trailing_dd,
        dd_type=args.dd_type,
        daily_loss_limit=args.daily_loss_limit,
        consistency_pct=args.consistency_pct,
        n_paths=args.n_paths,
        seed=args.seed,
    )
    print(pd.DataFrame(sweep).to_string(index=False))


if __name__ == "__main__":
    main()
