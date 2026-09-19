# QuantConnect (LEAN) Python port of tradingview/nq_vwap_momentum_strategy.pine.
#
# Same rules, same state machine, ported bar-for-bar from the Pine script:
#
#   LONG bias   : close > session VWAP, VWAP rising over the last N bars,
#                 and price up >= momentum_pct over the last M bars.
#   SHORT bias  : close < session VWAP, VWAP falling over the last N bars,
#                 and price down >= momentum_pct over the last M bars.
#   Trigger     : the FIRST red candle after a long bias turns on (pullback
#                 toward VWAP) / the FIRST green candle after a short bias
#                 turns on. Re-arms only once the bias condition goes false
#                 and true again.
#   Session     : no new entries 09:30-10:30 America/New_York, no new
#                 entries after 15:30, flatten everything at 16:55.
#   Trade caps  : one open position at a time, max 2 entries/day, trading
#                 stops for the day after 2 losing trades.
#   Exits       : fixed points, no trailing -- long -80/+40, short -80/+50.
#                 Futures "points" are already price units for NQ (1 index
#                 point == 1.0 in the quoted price), so unlike the Pine
#                 version (which divides by syminfo.mintick to get ticks for
#                 strategy.exit), here the point offsets are applied to
#                 price directly.
#
# Defaults assume a 5-minute chart, matching the Pine script. The
# "15 minutes" / "1 hour" windows are expressed as bar counts (3 and 12)
# for the same reason as the Pine version -- change them if you resample.
#
# This trades the continuous NQ future directly (DataNormalizationMode.Raw,
# so absolute price levels are real traded prices -- required since the
# stop/target are fixed point offsets, not percentages). Raw mode has price
# discontinuities across contract rolls, so the algorithm flattens and
# resets its state whenever the mapped contract changes (OnSymbolChangedEvents)
# rather than trying to carry a position or bias episode across a roll.
#
# Not proven profitable -- same disclaimer as the Pine script and the rest
# of this repo. Validate with QuantConnect's Research/backtest tools,
# realistic fees/slippage, and multiple date ranges before considering it
# for paper or live trading.

from AlgorithmImports import *


class NQVWAPMomentumAlgorithm(QCAlgorithm):

    def Initialize(self):
        # ------------------------------------------------------------------
        # Backtest window / cash -- adjust to taste.
        # ------------------------------------------------------------------
        self.SetStartDate(2022, 1, 1)
        self.SetEndDate(2024, 1, 1)
        self.SetCash(100000)

        # All session-time logic below assumes algorithm time is Eastern.
        self.SetTimeZone(TimeZones.NewYork)

        # ------------------------------------------------------------------
        # Strategy inputs -- names mirror the Pine script's inputs 1:1.
        # ------------------------------------------------------------------
        self.vwap_slope_lookback = 3     # "past 15 minutes" as 5-min bars
        self.momentum_lookback = 12      # "past 1 hour" as 5-min bars
        self.momentum_pct = 0.1          # percent

        self.long_stop_points = 80.0
        self.long_target_points = 40.0
        self.short_stop_points = 80.0
        self.short_target_points = 50.0

        self.max_trades_per_day = 2
        self.max_losses_per_day = 2

        self.blocked_start_min = 9 * 60 + 30    # 09:30 ET
        self.blocked_end_min = 10 * 60 + 30     # 10:30 ET
        self.no_new_trades_min = 15 * 60 + 30   # 15:30 ET
        self.flatten_min = 16 * 60 + 55         # 16:55 ET

        self.order_size = 1  # contracts

        # Session VWAP resets at CME's ~18:00 ET Globex session open, which
        # is the "new trading day" boundary most futures data vendors use
        # (a 17:00-18:00 ET maintenance break splits sessions). Adjust if
        # your data/venue uses a different convention (e.g. midnight UTC).
        self.session_reset_hour = 18

        # ------------------------------------------------------------------
        # Instrument -- continuous NQ future, raw prices (see module docstring
        # for why raw rather than back-adjusted).
        # ------------------------------------------------------------------
        future = self.AddFuture(
            Futures.Indices.NASDAQ100EMini,
            resolution=Resolution.Minute,
            extendedMarketHours=True,
            dataMappingMode=DataMappingMode.OpenInterest,
            dataNormalizationMode=DataNormalizationMode.Raw,
            contractDepthOffset=0,
        )
        self.symbol = future.Symbol

        # 5-minute consolidator, tied to the canonical continuous symbol --
        # LEAN keeps feeding it the currently-mapped contract's bars.
        self.Consolidate(self.symbol, timedelta(minutes=5), self.OnFiveMinuteBar)

        # ------------------------------------------------------------------
        # VWAP accumulator state (manual, session-anchored -- QC's built-in
        # VWAP indicator is a plain rolling average, not session-reset).
        # ------------------------------------------------------------------
        self.cum_pv = 0.0
        self.cum_vol = 0.0
        self.current_session_date = None

        window_size = max(self.vwap_slope_lookback, self.momentum_lookback) + 1
        self.vwap_window = RollingWindow[float](window_size)
        self.close_window = RollingWindow[float](window_size)

        # ------------------------------------------------------------------
        # Trigger state machine (mirrors the Pine script's var bools).
        # ------------------------------------------------------------------
        self.long_bias_active = False
        self.long_fired = False
        self.short_bias_active = False
        self.short_fired = False

        # ------------------------------------------------------------------
        # Position / order-management state.
        # ------------------------------------------------------------------
        self.in_position = False
        self.pending_direction = 0     # +1 long, -1 short, while entry order is in flight
        self.entry_ticket = None
        self.entry_price = None
        self.entry_direction = 0
        self.exit_tickets = []         # stop + target (or the EOD liquidate ticket)

        # ------------------------------------------------------------------
        # Daily trade/loss counters.
        # ------------------------------------------------------------------
        self.trades_today = 0
        self.losses_today = 0

        self.Schedule.On(
            self.DateRules.EveryDay(self.symbol),
            self.TimeRules.At(0, 0),
            self.ResetDailyCounters,
        )
        self.Schedule.On(
            self.DateRules.EveryDay(self.symbol),
            self.TimeRules.At(16, 55),
            self.FlattenAtEndOfDay,
        )

        self.SetWarmUp(timedelta(days=3))

    # ----------------------------------------------------------------------
    # Daily resets / EOD flatten
    # ----------------------------------------------------------------------
    def ResetDailyCounters(self):
        self.trades_today = 0
        self.losses_today = 0

    def FlattenAtEndOfDay(self):
        if self.entry_ticket is not None and self.entry_ticket.Status not in (
            OrderStatus.Filled, OrderStatus.Canceled, OrderStatus.Invalid
        ):
            self.entry_ticket.Cancel()

        for ticket in self.exit_tickets:
            if ticket.Status not in (OrderStatus.Filled, OrderStatus.Canceled, OrderStatus.Invalid):
                ticket.Cancel()
        self.exit_tickets = []

        if self.Portfolio[self.symbol].Invested:
            liquidate_tickets = self.Liquidate(self.symbol, "eod_flatten")
            # Route the liquidation fill through the same exit-fill handling
            # (pnl / loss-count bookkeeping, state reset) as a stop/target.
            self.exit_tickets = list(liquidate_tickets)
        else:
            self._reset_position_state()

    def OnSymbolChangedEvents(self, symbolChangedEvents):
        # Contract roll on the continuous future -- raw prices are
        # discontinuous across this boundary, so don't try to carry a
        # position, a resting bracket, or a bias episode across it.
        for changed in symbolChangedEvents.Values:
            if changed.Symbol == self.symbol:
                self.Log(f"Contract roll {changed.OldSymbol} -> {changed.NewSymbol}: flattening.")
                self.FlattenAtEndOfDay()
                self.long_bias_active = False
                self.long_fired = False
                self.short_bias_active = False
                self.short_fired = False

    # ----------------------------------------------------------------------
    # Main 5-minute bar handler -- equivalent of the Pine script's per-bar
    # top-level execution.
    # ----------------------------------------------------------------------
    def OnFiveMinuteBar(self, bar: TradeBar):
        self._update_vwap(bar)
        self._update_windows(bar)

        if self.IsWarmingUp:
            return

        vwap_value = self._current_vwap()
        if vwap_value is None:
            return

        vwap_rising = (
            self.vwap_window.Count > self.vwap_slope_lookback
            and self.vwap_window[0] > self.vwap_window[self.vwap_slope_lookback]
        )
        vwap_falling = (
            self.vwap_window.Count > self.vwap_slope_lookback
            and self.vwap_window[0] < self.vwap_window[self.vwap_slope_lookback]
        )

        momentum_up = False
        momentum_down = False
        if self.close_window.Count > self.momentum_lookback:
            past_close = self.close_window[self.momentum_lookback]
            if past_close != 0:
                pct_change = (self.close_window[0] - past_close) / past_close * 100.0
                momentum_up = pct_change >= self.momentum_pct
                momentum_down = pct_change <= -self.momentum_pct

        long_bias = bar.Close > vwap_value and vwap_rising and momentum_up
        short_bias = bar.Close < vwap_value and vwap_falling and momentum_down

        # --- trigger state machine, mirrors the Pine script exactly -------
        if long_bias:
            if not self.long_bias_active:
                self.long_fired = False
            self.long_bias_active = True
        else:
            self.long_bias_active = False
            self.long_fired = False

        if short_bias:
            if not self.short_bias_active:
                self.short_fired = False
            self.short_bias_active = True
        else:
            self.short_bias_active = False
            self.short_fired = False

        red_candle = bar.Close < bar.Open
        green_candle = bar.Close > bar.Open

        long_signal = long_bias and red_candle and bar.Close > vwap_value and not self.long_fired
        short_signal = short_bias and green_candle and bar.Close < vwap_value and not self.short_fired

        if long_signal:
            self.long_fired = True
        if short_signal:
            self.short_fired = True

        # --- session / limit filters --------------------------------------
        minutes_of_day = self.Time.hour * 60 + self.Time.minute
        in_blocked_window = self.blocked_start_min <= minutes_of_day < self.blocked_end_min
        past_no_new_trades = minutes_of_day >= self.no_new_trades_min
        past_flatten_time = minutes_of_day >= self.flatten_min

        can_enter = (
            not self.in_position
            and not in_blocked_window
            and not past_no_new_trades
            and not past_flatten_time
            and self.trades_today < self.max_trades_per_day
            and self.losses_today < self.max_losses_per_day
        )

        if long_signal and can_enter:
            self._submit_entry(direction=1)
        elif short_signal and can_enter:
            self._submit_entry(direction=-1)

    # ----------------------------------------------------------------------
    # VWAP / rolling-window bookkeeping
    # ----------------------------------------------------------------------
    def _session_date_for(self, dt):
        # CME "trade date": bars from session_reset_hour onward belong to
        # the next calendar day's session.
        if dt.hour >= self.session_reset_hour:
            return (dt + timedelta(days=1)).date()
        return dt.date()

    def _update_vwap(self, bar: TradeBar):
        session_date = self._session_date_for(bar.Time)
        if session_date != self.current_session_date:
            self.current_session_date = session_date
            self.cum_pv = 0.0
            self.cum_vol = 0.0

        typical_price = (bar.High + bar.Low + bar.Close) / 3.0
        self.cum_pv += typical_price * bar.Volume
        self.cum_vol += bar.Volume

    def _current_vwap(self):
        if self.cum_vol <= 0:
            return None
        return self.cum_pv / self.cum_vol

    def _update_windows(self, bar: TradeBar):
        vwap_value = self._current_vwap()
        if vwap_value is not None:
            self.vwap_window.Add(vwap_value)
        self.close_window.Add(float(bar.Close))

    # ----------------------------------------------------------------------
    # Order management
    # ----------------------------------------------------------------------
    def _submit_entry(self, direction: int):
        quantity = direction * self.order_size
        self.entry_ticket = self.MarketOrder(self.symbol, quantity)
        self.pending_direction = direction
        self.in_position = True
        self.trades_today += 1

    def OnOrderEvent(self, orderEvent):
        if orderEvent.Status != OrderStatus.Filled:
            return

        if self.entry_ticket is not None and orderEvent.OrderId == self.entry_ticket.OrderId:
            self._on_entry_filled(orderEvent.FillPrice)
            return

        exit_ids = {t.OrderId for t in self.exit_tickets}
        if orderEvent.OrderId in exit_ids:
            self._on_exit_filled(orderEvent.FillPrice)

    def _on_entry_filled(self, fill_price: float):
        self.entry_price = fill_price
        self.entry_direction = self.pending_direction
        self.entry_ticket = None

        exit_quantity = -self.entry_direction * self.order_size
        if self.entry_direction > 0:
            stop_price = self.entry_price - self.long_stop_points
            target_price = self.entry_price + self.long_target_points
        else:
            stop_price = self.entry_price + self.short_stop_points
            target_price = self.entry_price - self.short_target_points

        stop_ticket = self.StopMarketOrder(self.symbol, exit_quantity, stop_price)
        target_ticket = self.LimitOrder(self.symbol, exit_quantity, target_price)
        self.exit_tickets = [stop_ticket, target_ticket]

    def _on_exit_filled(self, fill_price: float):
        if self.entry_price is not None:
            pnl_points = (fill_price - self.entry_price) * self.entry_direction
            if pnl_points < 0:
                self.losses_today += 1

        for ticket in self.exit_tickets:
            if ticket.Status not in (OrderStatus.Filled, OrderStatus.Canceled, OrderStatus.Invalid):
                ticket.Cancel()

        self._reset_position_state()

    def _reset_position_state(self):
        self.in_position = False
        self.pending_direction = 0
        self.entry_ticket = None
        self.entry_price = None
        self.entry_direction = 0
        self.exit_tickets = []
