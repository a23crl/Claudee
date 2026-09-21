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

# Opening Range Breakout — TradingView (Pine Script v5)

`opening_range_breakout_strategy.pine` is a from-scratch Pine implementation
of the classic ORB concept (Toby Crabel / Mark Fisher, and the version
popularized more recently by vendors like LuxAlgo): mark the high/low made
during a configurable opening window each day, then trade confirmed breaks
of that range with a stop on the opposite side and a target sized to the
range's width (or an optional ATR trailing stop). It's an original build of
the publicly-documented mechanics — not a copy of any vendor's proprietary
source — written to match this repo's Pine conventions (risk-based position
sizing, session-end flatten, data-coverage table, alerts).

There's no Python counterpart for this one; it's Pine-only.

## Setup

1. Open a TradingView chart on an **intraday interval whose length divides
   evenly into both the opening-range window and the entry window** (e.g.
   1m/5m/15m for a 15-minute opening range) for a liquid symbol with real
   volume.
2. Pine Editor → New blank strategy → paste in
   `opening_range_breakout_strategy.pine` → Add to chart.
3. Open **Strategy Tester → Properties** and set realistic commission and
   slippage for your instrument/broker.
4. Tune the inputs, grouped as:
   - **Session & Range**: the opening-range window and timezone, the
     allowed entry window, and min/max range size filters (in ATR
     multiples) to skip days where the range is too tight or already blown
     out.
   - **Entry Rules**: close-beyond-range vs. wick-beyond-range
     confirmation, breakout volume filter, one-trade-per-side-per-day cap,
     and whether shorts are allowed.
   - **Risk Management**: stop buffer beyond the range, a fixed target as a
     multiple of range width, or an ATR trailing stop instead; risk-per-trade
     and max exposure as a % of equity.
   - **Session & Filters**: optional backtest date range.

## Notes

- **Volume filter**: on for a reason — breakout volume confirmation cuts
  down on false breaks — but disable it (`Require breakout volume
  confirmation`) for symbols without reliable volume data (spot FX).
- **Timezone**: the opening-range and entry-window inputs are matched
  against wall-clock time via `time(timeframe.period, session, timezone)`;
  make sure the timezone string matches the session you actually mean
  (e.g. `America/New_York` for the U.S. cash open), not the chart's display
  timezone.
- Same plan-bar-limit caveat as the VWAP script above — check the
  data-coverage table before trusting a backtest's trade count.
- Same execution-model caveats as the VWAP script (entry fills, sizing off
  signal-bar close, session-end flatten via `session.islastbar`,
  commission/slippage in Properties, stop-vs-target-in-same-bar ambiguity)
  apply here too.
