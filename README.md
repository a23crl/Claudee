# VWAP Pullback

A research project to test whether a VWAP pullback strategy has a real,
robust edge before risking money on it live. It includes signal generation,
an event-driven backtester, performance metrics, plots, and a parameter
sensitivity sweep.

**This is a research tool, not a live trading system.** Nothing here places
real orders. It exists to help you decide *whether* implementing this
strategy live is worth doing.

A TradingView port (`pinescript/vwap_pullback.pine`) mirrors the same logic
as a `strategy()` script, for backtesting directly against TradingView's own
data. Its comments cover a subtlety worth knowing up front: **TradingView
plans cap total historical bars** (commonly 5,000-10,000 on lower tiers),
which limits calendar coverage hardest on small timeframes (10,000 bars is
~1 month on a 1-minute chart but ~1.5 years on a 15-minute chart). The
script draws a small table on the chart reporting the actual bar count and
date range you got, so you can judge whether the sample is even large
enough to trust (see point 5 below).

## The strategy

Intraday, trend-following, mean-reversion-to-VWAP:

1. **Establish bias.** Price extends `min_extension_atr` (in ATR units) away
   from the session VWAP — up for a long bias, down for a short bias.
2. **Let the bias hold.** It must persist for `min_trend_bars` bars without
   a strong extension in the opposite direction (otherwise the bias flips).
3. **Wait for the pullback.** Price retraces back to within
   `pullback_atr_mult` ATR of VWAP.
4. **Trigger on reclaim.** A bar that closes back on the biased side of VWAP,
   closes in the direction of the bias (bullish/bearish body), and
   (optionally) breaks the prior bar's high/low — that's the entry signal.
5. **Manage risk.** Stop loss at the pullback's swing low/high (plus a small
   ATR buffer); take-profit at `reward_r` multiples of that initial risk;
   forced flat at the end of the session (VWAP resets daily, so the
   reference level goes stale overnight and no positions are held over
   close).

All of this is implemented in `vwap_pullback/strategy.py`.

## Why the backtest is built the way it is

The engine (`vwap_pullback/backtest.py`) is deliberately conservative so it
doesn't flatter the strategy:

- A signal on bar *i*'s close fills at bar *i+1*'s **open** — never the same
  bar, so there's no lookahead bias.
- Slippage and commission are charged on every entry and exit.
- If a bar's range touches both the stop and the target, the **stop wins**
  (worst case for a pair of resting orders).
- Position size is chosen so `(entry − stop) × size == risk_pct × equity`,
  capped by `max_gross_exposure_pct`.

## Quickstart

```bash
pip install -r requirements.txt

# Sanity-check the mechanics with synthetic data (no network needed)
python run_backtest.py --synthetic trending --days 250
python run_backtest.py --synthetic random_walk --days 250   # should show NO edge

# Real data (run this on a machine with internet access to Yahoo Finance)
python run_backtest.py --ticker SPY --interval 5m --period 60d

# Your own intraday OHLCV export
python run_backtest.py --csv path/to/bars.csv
```

Each run prints a metrics report and writes `equity_curve.png`,
`drawdown.png`, `price_trades.png`, and `trades.csv` to `--out-dir`
(default `output/`).

Run the parameter sensitivity sweep:

```bash
python sweep.py --synthetic trending --days 250
python sweep.py --ticker SPY --interval 5m --period 60d
```

This runs a grid of `min_extension_atr` / `pullback_atr_mult` / `reward_r`
combinations and reports how much Sharpe/return swing across them. A
strategy whose results flip from strongly positive to negative on small
parameter nudges is likely fit to noise, not a real edge — don't trust a
single lucky cell.

Run the test suite:

```bash
pytest tests/ -v
```

The tests include a hand-computed backtest arithmetic check (entry/exit
fills, slippage, commission, sizing, R-multiples) and a check that the
strategy fires on manufactured trend/pullback patterns but not on flat
noise.

## Data sources

- **`--synthetic trending`**: manufactured trend + pullback-to-anchor
  structure, for testing the mechanics offline. Not real market behavior —
  don't use its results to judge live viability.
- **`--synthetic random_walk`**: pure noise, no exploitable structure. If
  the strategy shows a strong positive edge here, that's a sign of a bug
  (most likely lookahead bias), not alpha. In this project's own test run,
  the strategy *loses* money on random-walk data (negative Sharpe/expectancy,
  as expected once commissions and slippage are included) — that's the
  correct result.
- **`--ticker` (yfinance)**: real historical bars. This needs outbound
  internet access to Yahoo Finance, which may be unavailable in a sandboxed
  environment — run it on your own machine. Note yfinance's intraday
  history limits: ~60 days for 1-minute bars, ~730 days for 5m/15m/1h bars.
- **`--csv`**: any OHLCV data you already have (broker export, a vendor
  feed, previously downloaded bars). Needs a timestamp column plus
  open/high/low/close/volume.

## Deciding if it's worth going live

Running one backtest on one ticker and seeing a positive number is **not**
enough evidence. Before considering live capital:

1. **Use real data, multiple instruments, multiple time periods.** Test on
   several liquid tickers (not just one) and several non-overlapping date
   ranges. A strategy that only works on one specific stock/period is
   probably curve-fit.
2. **Check the parameter sweep.** Use `sweep.py` on real data. If
   performance is only good in a narrow island of parameter space, be
   skeptical.
3. **Split in/out of sample.** Tune parameters on one period, test unchanged
   on a later, untouched period. Performance should hold up reasonably well.
4. **Stress the cost assumptions.** `--commission-bps` and `--slippage-bps`
   here are placeholders — replace them with your actual broker's costs and
   a realistic estimate of market impact for your position size. Intraday
   mean-reversion strategies are notoriously cost-sensitive; a strategy that
   only works at 0 bps of costs is not a strategy.
5. **Check trade count and capacity.** Too few trades (as in these
   examples) means the performance metrics are statistically unreliable —
   you want enough trades across enough distinct market conditions to trust
   the win rate/profit factor.
6. **Paper trade before funding it.** Once the backtest evidence looks
   robust, run it against a live/delayed data feed on paper for a meaningful
   stretch before committing real capital — backtests never capture 100% of
   real execution friction (partial fills, latency, data gaps).

If it fails any of these, the honest conclusion is "not yet" — the code
here is meant to help you find that out cheaply, before finding it out with
real money.

## Running it on TradingView

`tradingview/vwap_pullback_strategy.pine` is a Pine Script v5 port of the
same strategy (same VWAP/ATR bias-pullback-trigger state machine, same
fixed-stop/R-multiple-target risk model, same session flatten), for use in
TradingView's Strategy Tester or as a live-alert source. See
`tradingview/README.md` for setup and — importantly — how its execution
model differs from the Python backtester above.

## Project layout

```
vwap_pullback/
  data.py        # CSV / yfinance loaders
  synthetic.py   # synthetic OHLCV generator (trending / random_walk)
  indicators.py  # session VWAP, ATR, EMA
  strategy.py    # signal generation (VWAPPullbackParams, generate_signals)
  backtest.py    # event-driven backtester (BacktestParams, run_backtest)
  metrics.py     # performance metrics + report formatting
  report.py      # equity curve / drawdown / price+trades plots
run_backtest.py  # CLI: run one backtest end-to-end
sweep.py         # CLI: parameter sensitivity grid search
tests/           # pytest unit tests
tradingview/     # Pine Script v5 port for TradingView's Strategy Tester / alerts
```
