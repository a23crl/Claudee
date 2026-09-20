# QuantConnect (LEAN) Python port of tradingview/nq_vwap_momentum_strategy.pine.
#
# Written against LEAN's PEP8/snake_case Python API (initialize, on_data,
# self.add_future, Resolution.MINUTE, etc.) -- verified against
# QuantConnect/Lean's own current example algorithms (BasicTemplateFuturesAlgorithm.py,
# ScheduledEventsAlgorithm.py, ContinuousFutureRegressionAlgorithm.py,
# StopLimitOrderRegressionAlgorithm.py, RollingWindowAlgorithm.py,
# ConsolidateRegressionAlgorithm.py) since some Cloud IDE projects' engine
# builds no longer accept the older PascalCase C#-style names (SetStartDate,
# AddFuture, Resolution.Minute, ...) that an earlier version of this file used.
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
# This trades the continuous NQ future directly (DataNormalizationMode.RAW,
# so absolute price levels are real traded prices -- required since the
# stop/target are fixed point offsets, not percentages). Raw mode has price
# discontinuities across contract rolls, so the algorithm flattens and
# resets its state whenever the mapped contract changes (detected via
# data.symbol_changed_events in on_data) rather than trying to carry a
# position or bias episode across a roll.
#
# Not proven profitable -- same disclaimer as the Pine script and the rest
# of this repo. Validate with QuantConnect's Research/backtest tools,
# realistic fees/slippage, and multiple date ranges before considering it
# for paper or live trading.

from AlgorithmImports import *


class NQVWAPMomentumAlgorithm(QCAlgorithm):

    def initialize(self):
        # ------------------------------------------------------------------
        # Backtest window / cash -- adjust to taste.
        # ------------------------------------------------------------------
        self.set_start_date(2022, 1, 1)
        self.set_end_date(2024, 1, 1)
        self.set_cash(100000)

        # All session-time logic below assumes algorithm time is Eastern.
        # Passed as a plain IANA string (documented, supported) rather than
        # a TimeZones.* constant, since that enum class's exact Python
        # attribute spelling isn't confirmed against this engine build.
        self.set_time_zone("America/New_York")

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
        # for why raw rather than back-adjusted). "NQ" + Market.CME is used
        # directly instead of Futures.Indices.NASDAQ_100_E_MINI so the symbol
        # doesn't depend on that constant's exact generated spelling.
        # ------------------------------------------------------------------
        future = self.add_future(
            "NQ",
            market=Market.CME,
            resolution=Resolution.MINUTE,
            extended_market_hours=True,
            data_mapping_mode=DataMappingMode.OPEN_INTEREST,
            data_normalization_mode=DataNormalizationMode.RAW,
            contract_depth_offset=0,
        )
        self._symbol = future.symbol

        # 5-minute consolidator, tied to the canonical continuous symbol --
        # LEAN keeps feeding it the currently-mapped contract's bars.
        self.consolidate(self._symbol, timedelta(minutes=5), self.on_five_minute_bar)

        # ------------------------------------------------------------------
        # VWAP accumulator state (manual, session-anchored -- QC's built-in
        # VWAP indicator is a plain rolling average, not session-reset).
        # ------------------------------------------------------------------
        self.cum_pv = 0.0
        self.cum_vol = 0.0
        self.current_session_date = None

        window_size = max(self.vwap_slope_lookback, self.momentum_lookback) + 1
        self.vwap_window = RollingWindow(window_size)
        self.close_window = RollingWindow(window_size)

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
        # The actual tradable contract (self._symbol is the canonical
        # continuous future used for data/consolidation; orders must go on
        # the currently-mapped underlying contract instead). Captured once
        # at entry time and reused for that trade's stop/target/liquidate
        # so it can't drift if a roll happens to change the mapping mid-trade.
        self.active_contract_symbol = None

        # ------------------------------------------------------------------
        # Daily trade/loss counters.
        # ------------------------------------------------------------------
        self.trades_today = 0
        self.losses_today = 0

        self.schedule.on(
            self.date_rules.every_day(self._symbol),
            self.time_rules.at(0, 0),
            self.reset_daily_counters,
        )
        self.schedule.on(
            self.date_rules.every_day(self._symbol),
            self.time_rules.at(16, 55),
            self.flatten_at_end_of_day,
        )

        self.set_warm_up(timedelta(days=3))

    # ----------------------------------------------------------------------
    # Slice handler -- only used to catch contract-roll events; all trading
    # logic runs in on_five_minute_bar via the consolidator above.
    # ----------------------------------------------------------------------
    def on_data(self, data: Slice):
        for changed_event in data.symbol_changed_events.values():
            if changed_event.symbol == self._symbol:
                # Raw prices are discontinuous across a roll, so don't try
                # to carry a position, a resting bracket, or a bias episode
                # across it -- flatten and reset instead.
                self.log(f"Contract roll {changed_event.old_symbol} -> {changed_event.new_symbol}: flattening.")
                self.flatten_at_end_of_day()
                self.long_bias_active = False
                self.long_fired = False
                self.short_bias_active = False
                self.short_fired = False

    # ----------------------------------------------------------------------
    # Daily resets / EOD flatten
    # ----------------------------------------------------------------------
    def reset_daily_counters(self):
        self.trades_today = 0
        self.losses_today = 0

    def flatten_at_end_of_day(self):
        if self.entry_ticket is not None and self.entry_ticket.status not in (
            OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.INVALID
        ):
            self.entry_ticket.cancel()

        for ticket in self.exit_tickets:
            if ticket.status not in (OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.INVALID):
                ticket.cancel()
        self.exit_tickets = []

        if self.active_contract_symbol is not None and self.portfolio[self.active_contract_symbol].invested:
            liquidate_tickets = self.liquidate(self.active_contract_symbol, "eod_flatten")
            # Route the liquidation fill through the same exit-fill handling
            # (pnl / loss-count bookkeeping, state reset) as a stop/target.
            self.exit_tickets = list(liquidate_tickets)
        else:
            self._reset_position_state()

    # ----------------------------------------------------------------------
    # Main 5-minute bar handler -- equivalent of the Pine script's per-bar
    # top-level execution.
    # ----------------------------------------------------------------------
    def on_five_minute_bar(self, bar: TradeBar):
        self._update_vwap(bar)
        self._update_windows(bar)

        if self.is_warming_up:
            return

        vwap_value = self._current_vwap()
        if vwap_value is None:
            return

        vwap_rising = (
            self.vwap_window.count > self.vwap_slope_lookback
            and self.vwap_window[0] > self.vwap_window[self.vwap_slope_lookback]
        )
        vwap_falling = (
            self.vwap_window.count > self.vwap_slope_lookback
            and self.vwap_window[0] < self.vwap_window[self.vwap_slope_lookback]
        )

        momentum_up = False
        momentum_down = False
        if self.close_window.count > self.momentum_lookback:
            past_close = self.close_window[self.momentum_lookback]
            if past_close != 0:
                pct_change = (self.close_window[0] - past_close) / past_close * 100.0
                momentum_up = pct_change >= self.momentum_pct
                momentum_down = pct_change <= -self.momentum_pct

        long_bias = bar.close > vwap_value and vwap_rising and momentum_up
        short_bias = bar.close < vwap_value and vwap_falling and momentum_down

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

        red_candle = bar.close < bar.open
        green_candle = bar.close > bar.open

        long_signal = long_bias and red_candle and bar.close > vwap_value and not self.long_fired
        short_signal = short_bias and green_candle and bar.close < vwap_value and not self.short_fired

        if long_signal:
            self.long_fired = True
        if short_signal:
            self.short_fired = True

        # --- session / limit filters --------------------------------------
        minutes_of_day = self.time.hour * 60 + self.time.minute
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
        session_date = self._session_date_for(bar.time)
        if session_date != self.current_session_date:
            self.current_session_date = session_date
            self.cum_pv = 0.0
            self.cum_vol = 0.0

        typical_price = (bar.high + bar.low + bar.close) / 3.0
        self.cum_pv += typical_price * bar.volume
        self.cum_vol += bar.volume

    def _current_vwap(self):
        if self.cum_vol <= 0:
            return None
        return self.cum_pv / self.cum_vol

    def _update_windows(self, bar: TradeBar):
        vwap_value = self._current_vwap()
        if vwap_value is not None:
            self.vwap_window.add(vwap_value)
        self.close_window.add(float(bar.close))

    # ----------------------------------------------------------------------
    # Order management
    # ----------------------------------------------------------------------
    def _submit_entry(self, direction: int):
        # The canonical continuous symbol (self._symbol) is not itself
        # tradable -- only the currently-mapped underlying contract is.
        self.active_contract_symbol = self.securities[self._symbol].mapped
        quantity = direction * self.order_size
        self.entry_ticket = self.market_order(self.active_contract_symbol, quantity)
        self.pending_direction = direction
        self.in_position = True
        self.trades_today += 1

    def on_order_event(self, order_event: OrderEvent):
        if order_event.status != OrderStatus.FILLED:
            return

        if self.entry_ticket is not None and order_event.order_id == self.entry_ticket.order_id:
            self._on_entry_filled(order_event.fill_price)
            return

        exit_ids = {t.order_id for t in self.exit_tickets}
        if order_event.order_id in exit_ids:
            self._on_exit_filled(order_event.fill_price)

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

        stop_ticket = self.stop_market_order(self.active_contract_symbol, exit_quantity, stop_price)
        target_ticket = self.limit_order(self.active_contract_symbol, exit_quantity, target_price)
        self.exit_tickets = [stop_ticket, target_ticket]

    def _on_exit_filled(self, fill_price: float):
        if self.entry_price is not None:
            pnl_points = (fill_price - self.entry_price) * self.entry_direction
            if pnl_points < 0:
                self.losses_today += 1

        for ticket in self.exit_tickets:
            if ticket.status not in (OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.INVALID):
                ticket.cancel()

        self._reset_position_state()

    def _reset_position_state(self):
        self.in_position = False
        self.pending_direction = 0
        self.entry_ticket = None
        self.entry_price = None
        self.entry_direction = 0
        self.exit_tickets = []
        self.active_contract_symbol = None
