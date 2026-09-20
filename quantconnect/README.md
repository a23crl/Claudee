# QuantConnect (LEAN Python)

`nq_vwap_momentum_algorithm.py` is a QuantConnect (LEAN) Python port of
`tradingview/nq_vwap_momentum_strategy.pine` — same VWAP-slope + 1-hour
momentum bias, same first-pullback-candle trigger state machine, same
session/trade/loss limits, same fixed-point stop/target exits. It is a
separate, from-scratch translation, not tied to the ATR-based Python
research project at the repo root (`vwap_pullback/`) or to
`tradingview/vwap_pullback_strategy.pine`.

## What it trades

The continuous NQ (Nasdaq-100 E-mini) future, requested as the raw ticker
`"NQ"` on `Market.CME` (rather than the `Futures.Indices.*` constant — see
"A note on the API style" below), with `DataNormalizationMode.RAW` prices.
Raw (not back-adjusted) prices are required here because the exit rule is a
fixed point offset (e.g. −80/+40), not a percentage — back-adjusted prices
would shift historical stop/target levels away from what they'd actually
have been. The tradeoff is a price discontinuity at every contract roll,
which is why the algorithm flattens and resets its bias/trigger state on a
roll (detected via `data.symbol_changed_events` in `on_data`) rather than
trying to carry a position or an in-progress pullback episode across it.

If you'd rather trade **MNQ** (Micro E-mini Nasdaq-100), swap the ticker
`"NQ"` for `"MNQ"` in `initialize` — the point-based exit math is unaffected
(MNQ points equal NQ points, only the multiplier/contract size differs).

## A note on the API style

QuantConnect's Python API has two casing conventions: the original
C#-style PascalCase (`SetStartDate`, `AddFuture`, `Resolution.Minute`) and a
newer PEP8/snake_case style (`set_start_date`, `add_future`,
`Resolution.MINUTE`) that some Cloud IDE projects' engine builds require
exclusively — the PascalCase names simply don't resolve on those. This file
is written entirely in the snake_case style, verified line-for-line against
QuantConnect/Lean's own current example algorithms (`BasicTemplateFuturesAlgorithm.py`,
`ScheduledEventsAlgorithm.py`, `ContinuousFutureRegressionAlgorithm.py`,
`StopLimitOrderRegressionAlgorithm.py`, `RollingWindowAlgorithm.py`,
`ConsolidateRegressionAlgorithm.py`). If your project's IDE flags any call
here as an unknown attribute, check that file's current spelling first —
the API does shift between LEAN versions.

One deliberate hedge: the future is requested via the raw ticker `"NQ"` +
`Market.CME` rather than a `Futures.Indices.NASDAQ_100_E_MINI`-style
constant. That constant almost certainly exists under that name (confirmed
by analogy with `Futures.Indices.SP_500_E_MINI` in QuantConnect's own
examples), but the raw ticker sidesteps depending on that guess entirely.

One naming pitfall worth flagging if you fork this: `QCAlgorithm` itself
has a built-in `symbol(...)` method (converts a ticker string to a `Symbol`
object). Naming an instance field `self.symbol` shadows/collides with it,
which the type checker reports as "cannot assign to a method" plus a cascade
of unrelated-looking "no overload variant matches" errors on every later
call that reads `self.symbol` back (`consolidate`, `date_rules.every_day`,
`portfolio[...]`, `liquidate`, `market_order`, ...). This file stores it as
`self._symbol` instead, matching the underscore-prefixed instance-field
convention QuantConnect's own example algorithms use (`self._symbol`,
`self._future`, `self._buy_order_ticket`, ...).

## How the translation maps onto the Pine script

| Pine construct | Python/LEAN equivalent |
|---|---|
| 5-minute chart bars | `self.consolidate(self._symbol, timedelta(minutes=5), self.on_five_minute_bar)` |
| Session-anchored `cumPV`/`cumVol` VWAP | Manual `cum_pv`/`cum_vol` accumulators, reset on a session-date change (`_update_vwap`) |
| `vwapVal[N]`, `close[N]` | `RollingWindow`, indexed the same way (`window[0]` = current, `window[N]` = N bars back) |
| `var bool longBiasActive/longFired` state machine | Same fields as instance attributes, same transition logic |
| `hour(time, "America/New_York")` / `minute(...)` | `self.set_time_zone("America/New_York")` + `self.time.hour/minute` |
| Daily trade/loss counters, reset per NY day | `self.schedule.on(..., self.time_rules.at(0, 0), self.reset_daily_counters)` |
| `strategy.exit(profit=.../mintick, loss=.../mintick)` | `stop_market_order`/`limit_order` placed at `entry_price ± points` directly (futures points are already price units, no tick conversion needed) |
| `session.islastbar` flatten at 16:55 | `self.schedule.on(..., self.time_rules.at(16, 55), self.flatten_at_end_of_day)` |
| `OnSymbolChangedEvents` (contract roll) | Checked inside `on_data` via `data.symbol_changed_events.values()`, matching how QuantConnect's own `ContinuousFutureRegressionAlgorithm.py` does it |

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
   LEAN CLI project) and replace the contents of `main.py` with
   `nq_vwap_momentum_algorithm.py` (not the `.pine` file from the
   `tradingview/` folder — easy to grab the wrong one since both describe
   the same strategy).
2. Adjust `set_start_date`/`set_end_date`/`set_cash` in `initialize` for the
   backtest window you want.
3. Tune the strategy inputs at the top of `initialize` (lookback bar counts,
   stop/target points, session times, trade/loss caps) — they're plain
   instance attributes, not QC `Parameter`-decorated fields, so edit them
   directly or wire up `self.get_parameter(...)` yourself if you want to
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
