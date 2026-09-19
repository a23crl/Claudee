# TradingView (Pine Script v5)

Two independent strategies live here — they share a "session VWAP +
mean-reversion pullback" family resemblance but have different rules, so
don't mix up their inputs or results.

## `vwap_pullback_strategy.pine`

A TradingView port of the strategy implemented in `vwap_pullback/strategy.py`
and `vwap_pullback/backtest.py` at the repo root: intraday, trend-following,
mean-reversion-to-VWAP, using ATR-relative extension/pullback bands. See the
top-level `README.md` for the full write-up of the setup logic and, more
importantly, the checklist for deciding whether any backtest result is
strong enough to trust with real money. Nothing here is proven profitable —
treat it as a starting point for your own testing, not a signal to trade.

## `nq_vwap_momentum_strategy.pine`

A separately-specified strategy for NQ futures on the 5-minute chart, not
tied to the Python research project. Rules:

- **Long bias**: close above session VWAP, VWAP rising over the last 15
  minutes, and price up at least 0.1% over the last hour.
- **Short bias**: close below session VWAP, VWAP falling over the last 15
  minutes, and price down at least 0.1% over the last hour.
- **Trigger**: the first red candle pulling back toward VWAP after a long
  bias turns on; the first green candle pulling back toward VWAP after a
  short bias turns on. Only the first qualifying candle of each bias episode
  fires.
- **Session filters**: no new entries 09:30-10:30 America/New_York, no new
  entries after 15:30, everything flattened at 16:55.
- **Trade caps**: one open position at a time, max 2 entries/day, trading
  stops for the rest of the day after 2 losses.
- **Exits**: fixed points, no trailing — long risks 80 points to make 40;
  short risks 80 points to make 50. Converted to ticks via
  `syminfo.mintick` so it's correct for whichever NQ/MNQ contract you're on.

All of the above (lookback bar counts, point stops/targets, session times,
trade/loss caps) are script inputs, grouped as Setup / Risk Management /
Session & Limits — the 15-minute and 1-hour windows are expressed as bar
counts (default 3 and 12) assuming a 5-minute chart; adjust those two inputs
if you run it on a different timeframe.

## Plan bar limits

Lower TradingView plan tiers cap total historical bars a chart can load
(as low as 10,000). That cap is on bar count, not calendar time, so it's
much more restrictive on small timeframes: 10,000 bars is only ~1 month
of history on a 1-minute chart, but ~6 months on 5-minute and ~1.5 years
on 15-minute. Both scripts draw a small table in the chart's top-right
corner — check bar count/date range (or trade/loss counters, for the NQ
script) before trusting a backtest's metrics, and prefer a higher timeframe
if the sample looks too small (see the top-level README, "Deciding if it's
worth going live", point 5, on trade-count reliability).

## Setup

1. Open a TradingView chart on an **intraday interval** for a liquid symbol
   with real volume (VWAP needs it) — 1m–15m for `vwap_pullback_strategy.pine`,
   the 5-minute chart for `nq_vwap_momentum_strategy.pine` (its "15 minute"
   and "1 hour" lookbacks are bar counts tuned for 5m bars). Both scripts
   reset VWAP and their bias/pullback state every session, so neither is
   meaningful on daily+ bars.
2. Pine Editor → New blank strategy → paste in the script you want → Add to
   chart.
3. Open **Strategy Tester → Properties** and set realistic commission and
   slippage for your instrument/broker (both scripts ship placeholder
   defaults — percent-of-notional for `vwap_pullback_strategy.pine`,
   cash-per-contract for `nq_vwap_momentum_strategy.pine` — same spirit as
   `--commission-bps`/`--slippage-bps` in `run_backtest.py`, but calibrate
   to your actual futures broker fees).
4. Tune the inputs. In `vwap_pullback_strategy.pine` they're grouped as
   VWAP/ATR, Entry Rules, Risk Management, Session & Filters and map 1:1 to
   `VWAPPullbackParams`/`BacktestParams` in the Python version, so a
   parameter sweep you like in `sweep.py` translates directly here. In
   `nq_vwap_momentum_strategy.pine` they're grouped as Setup, Risk
   Management, Session & Limits and correspond directly to the rules listed
   above.

## How `vwap_pullback_strategy.pine` differs from the Python backtester

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

- **Alerts → webhook**: both scripts raise `alertcondition()`s for
  long/short signals. Point a TradingView alert at a webhook URL and have
  your own execution bridge (or a broker's supported webhook integration)
  place the order. Validate that bridge as carefully as the strategy itself.
- **Supported broker/paper integrations**: some brokers TradingView
  integrates with can execute strategy alerts directly — check your
  broker's TradingView integration docs.

Either way, paper trade the live signal path for a meaningful stretch
before risking capital — a Pine backtest, like the Python one, can't fully
capture real execution friction (latency, partial fills, data gaps).
