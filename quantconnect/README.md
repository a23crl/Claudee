# QuantConnect (LEAN Python)

`nq_vwap_momentum_algorithm.py` is a QuantConnect (LEAN) Python port of
`tradingview/nq_vwap_momentum_strategy.pine` — same VWAP-slope + 1-hour
momentum bias, same first-pullback-candle trigger state machine, same
session/trade/loss limits, same fixed-point stop/target exits. It is a
separate, from-scratch translation, not tied to the ATR-based Python
research project at the repo root (`vwap_pullback/`) or to
`tradingview/vwap_pullback_strategy.pine`.

## What it trades

The continuous NQ (Nasdaq-100 E-mini) future, with `DataNormalizationMode.Raw`
prices. Raw (not back-adjusted) prices are required here because the exit
rule is a fixed point offset (e.g. −80/+40), not a percentage — back-adjusted
prices would shift historical stop/target levels away from what they'd
actually have been. The tradeoff is a price discontinuity at every contract
roll, which is why the algorithm flattens and resets its bias/trigger state
in `OnSymbolChangedEvents` rather than trying to carry a position or an
in-progress pullback episode across a roll.

If you'd rather trade **MNQ** (Micro E-mini Nasdaq-100), swap
`Futures.Indices.NASDAQ100EMini` for `Futures.Indices.MicroNASDAQ100EMini` in
`Initialize` — the point-based exit math is unaffected (MNQ points equal NQ
points, only the multiplier/contract size differs).

## How the translation maps onto the Pine script

| Pine construct | Python/LEAN equivalent |
|---|---|
| 5-minute chart bars | `self.Consolidate(self.symbol, timedelta(minutes=5), self.OnFiveMinuteBar)` |
| Session-anchored `cumPV`/`cumVol` VWAP | Manual `cum_pv`/`cum_vol` accumulators, reset on a session-date change (`_update_vwap`) |
| `vwapVal[N]`, `close[N]` | `RollingWindow[float]`, indexed the same way (`window[0]` = current, `window[N]` = N bars back) |
| `var bool longBiasActive/longFired` state machine | Same fields as instance attributes, same transition logic |
| `hour(time, "America/New_York")` / `minute(...)` | `self.SetTimeZone(TimeZones.NewYork)` + `self.Time.hour/minute` |
| Daily trade/loss counters, reset per NY day | `self.Schedule.On(..., self.TimeRules.At(0, 0), self.ResetDailyCounters)` |
| `strategy.exit(profit=.../mintick, loss=.../mintick)` | `StopMarketOrder`/`LimitOrder` placed at `entry_price ± points` directly (futures points are already price units, no tick conversion needed) |
| `session.islastbar` flatten at 16:55 | `self.Schedule.On(..., self.TimeRules.At(16, 55), self.FlattenAtEndOfDay)` |

One behavioral difference worth knowing: the Pine script's stop/target are
both submitted via `strategy.exit` and TradingView's Strategy Tester decides
which fills first if a single bar's range touches both. This algorithm
submits a real stop order and a real limit order and lets LEAN's order
matching engine (using the underlying minute-resolution data, not just the
5-minute bar's OHLC) decide fill order and price — closer to how it would
actually execute live, but not guaranteed to match the Pine backtest
trade-for-trade.

## Setup

1. Create a new Python algorithm project in the QuantConnect IDE (or a local
   LEAN CLI project) and drop in `nq_vwap_momentum_algorithm.py` as
   `main.py`.
2. Adjust `SetStartDate`/`SetEndDate`/`SetCash` in `Initialize` for the
   backtest window you want.
3. Tune the strategy inputs at the top of `Initialize` (lookback bar counts,
   stop/target points, session times, trade/loss caps) — they're plain
   instance attributes, not QC `Parameter`-decorated fields, so edit them
   directly or wire up `self.GetParameter(...)` yourself if you want to
   sweep them via QuantConnect's optimizer.
4. Run the backtest. Check the Orders tab to confirm entries are landing
   inside the intended session windows and that stop/target brackets are
   getting placed on every fill.

## Known simplifications / things to validate before trusting results

- **Fees/slippage**: this uses whatever QuantConnect's default brokerage
  model charges for futures; set a `BrokerageModel`/fee model matching your
  actual broker before drawing conclusions, the same way the Pine script's
  `commission_value` placeholder needs calibrating.
- **Rollover handling**: flattening on every contract roll is conservative
  (it forfeits an open position rather than rolling it), but it keeps the
  raw-price stop/target math honest across the discontinuity. If you need
  positions to survive a roll, you'll have to rewrite that part.
- **Order fills**: stop/limit orders fill against LEAN's minute-resolution
  future data, which is more realistic than the Pine backtester's bar-OHLC
  assumption but still not a live fill — paper trade before risking capital,
  same checklist as the top-level README's "Deciding if it's worth going
  live" section.
- **VWAP session boundary**: resets at 18:00 America/New_York (`session_reset_hour`),
  matching the CME Globex session convention most futures data vendors use.
  If your data source defines "trading day" differently, adjust that input.
