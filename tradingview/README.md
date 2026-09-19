# VWAP Pullback — TradingView (Pine Script v5)

`vwap_pullback_strategy.pine` is a TradingView port of the same strategy
implemented in `vwap_pullback/strategy.py` and `vwap_pullback/backtest.py` at
the repo root: intraday, trend-following, mean-reversion-to-VWAP. See the
top-level `README.md` for the full write-up of the setup logic and, more
importantly, the checklist for deciding whether any backtest result is
strong enough to trust with real money. Nothing here is proven profitable —
treat it as a starting point for your own testing, not a signal to trade.

## Plan bar limits

Lower TradingView plan tiers cap total historical bars a chart can load
(as low as 10,000). That cap is on bar count, not calendar time, so it's
much more restrictive on small timeframes: 10,000 bars is only ~1 month
of history on a 1-minute chart, but ~6 months on 5-minute and ~1.5 years
on 15-minute. The script draws a small table in the chart's top-right
corner showing the actual bar count and date range you got — check it
before trusting a backtest's metrics, and prefer a higher timeframe if the
sample looks too small (see the top-level README, "Deciding if it's worth
going live", point 5, on trade-count reliability).

## Setup

1. Open a TradingView chart on an **intraday interval** (1m–15m; the
   strategy resets VWAP and its bias/pullback state every session, so it
   isn't meaningful on daily+ bars) for a liquid symbol with real volume
   (VWAP needs it).
2. Pine Editor → New blank strategy → paste in `vwap_pullback_strategy.pine`
   → Add to chart.
3. Open **Strategy Tester → Properties** and set realistic commission and
   slippage for your instrument/broker (the script ships conservative
   placeholder defaults, same spirit as `--commission-bps`/`--slippage-bps`
   in `run_backtest.py`).
4. Tune the inputs (grouped as VWAP/ATR, Entry Rules, Risk Management,
   Session & Filters) — they map 1:1 to `VWAPPullbackParams` /
   `BacktestParams` in the Python version, so a parameter sweep you like in
   `sweep.py` translates directly here.

## How it differs from the Python backtester

Pine's execution model isn't identical to the custom backtester, so results
will diverge somewhat even with the same inputs on the same data:

- **Entry fills**: same as Python — a signal on bar *i*'s close is queued
  and fills at bar *i+1*'s open. This is Pine's default market-order timing,
  so no special handling was needed.
- **Position sizing**: `risk_pct × equity / (entry − stop)` is computed
  using the *signal bar's close* as a proxy for the (unknown) next-bar fill
  price, since Pine must know order size before submitting it. The Python
  backtester sizes off the actual next-bar-open fill. Minor discrepancy,
  same direction of bias either way.
- **Session-end flatten**: uses `session.islastbar`, which is the chart
  symbol's regular-session calendar, not a lookback over the data like the
  Python version's per-day grouping. Should match for regular-hours data.
- **Commission/slippage**: set in Strategy Tester → Properties, not as
  script inputs — Pine's model is percent-of-notional + ticks, not the
  flat bps-on-both-sides model in `BacktestParams`. Calibrate separately.
- **Stops vs. targets in the same bar**: Pine's Strategy Tester has its own
  assumption for which one fills first when a bar's range touches both; it
  is not necessarily "stop wins" like the Python engine. Check
  Strategy Tester → Properties → "Verify Price for Limit Orders" and be
  skeptical of any edge that depends on this.

## Going from backtest to live signals

TradingView's Strategy Tester is simulation only — a Pine `strategy()`
script does not place real orders by itself. To act on signals:

- **Alerts → webhook**: the script raises `alertcondition()`s for long/short
  signals. Point a TradingView alert at a webhook URL and have your own
  execution bridge (or a broker's supported webhook integration) place the
  order. Validate that bridge as carefully as the strategy itself.
- **Supported broker/paper integrations**: some brokers TradingView
  integrates with can execute strategy alerts directly — check your
  broker's TradingView integration docs.

Either way, paper trade the live signal path for a meaningful stretch
before risking capital — a Pine backtest, like the Python one, can't fully
capture real execution friction (latency, partial fills, data gaps).
