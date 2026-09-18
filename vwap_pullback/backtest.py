"""Event-driven, single-asset backtester for signals produced by strategy.generate_signals.

Execution model (deliberately conservative, to avoid flattering the strategy):
  - A signal generated on bar i's CLOSE is filled at bar i+1's OPEN (no
    lookahead). If bar i is the last bar of its session, the signal is
    dropped (no time left to hold it).
  - Slippage is applied against the trader on every fill (entries pay up,
    exits give back some edge).
  - Within a bar, if both the stop and the target are between that bar's
    low and high, the STOP is assumed to fill first (worst case for a
    resting exit-order pair). This likely understates real performance
    slightly and is intentional.
  - Positions are always flattened at the last bar of the session at that
    bar's close (VWAP resets daily; no overnight risk is modeled).
  - Position size is chosen so that (entry_price - stop_price) * size ==
    risk_pct * account equity at the time of entry, capped so notional
    exposure never exceeds max_gross_exposure_pct * equity.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class BacktestParams:
    initial_cash: float = 100_000.0
    risk_pct: float = 0.0075          # fraction of equity risked per trade (stop distance)
    reward_r: float = 2.0             # take-profit distance, as a multiple of initial risk (R)
    commission_bps: float = 1.0       # commission, in bps of notional, charged on entry AND exit
    slippage_bps: float = 1.0         # adverse slippage, in bps of price, on entry AND exit
    max_gross_exposure_pct: float = 1.0  # cap notional at entry as a fraction of equity
    allow_short: bool = True


def _apply_slippage(price: float, side: int, entering: bool, bps: float) -> float:
    """side: +1 long, -1 short. entering: True on entry, False on exit."""
    adverse = side if entering else -side
    return price * (1 + adverse * bps / 1e4)


def run_backtest(df: pd.DataFrame, params: BacktestParams = BacktestParams()) -> tuple[pd.DataFrame, pd.Series]:
    """Run the backtest.

    df must already have the columns produced by strategy.generate_signals
    (signal, stop_price, session_end) plus open/high/low/close.

    Returns (trades, equity_curve). equity_curve is indexed like df and
    mark-to-market at each bar's close.
    """
    n = len(df)
    open_ = df["open"].to_numpy()
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    close = df["close"].to_numpy()
    session_end = df["session_end"].to_numpy()
    signal = df["signal"].to_numpy()
    stop_price_col = df["stop_price"].to_numpy()

    cash = params.initial_cash
    position = 0.0        # signed shares; +ve long, -ve short
    entry_price = math.nan
    stop_price = math.nan
    target_price = math.nan
    entry_time = None
    side = 0

    pending_entry_side: int | None = None
    pending_stop = math.nan

    equity_curve = np.empty(n)
    trades = []

    for i in range(n):
        ts = df.index[i]

        # 1) Fill any pending entry at this bar's open.
        if pending_entry_side is not None and position == 0:
            side = pending_entry_side
            equity_now = cash
            raw_fill = open_[i]
            fill_price = _apply_slippage(raw_fill, side, entering=True, bps=params.slippage_bps)
            risk_per_share = abs(fill_price - pending_stop)

            size_shares = 0
            if risk_per_share > 0 and np.isfinite(risk_per_share):
                dollar_risk = equity_now * params.risk_pct
                size_shares = dollar_risk / risk_per_share
                max_notional = equity_now * params.max_gross_exposure_pct
                max_shares_by_notional = max_notional / fill_price
                size_shares = math.floor(min(size_shares, max_shares_by_notional))

            if size_shares > 0 and (side == 1 or params.allow_short):
                notional = size_shares * fill_price
                commission = notional * params.commission_bps / 1e4
                position = side * size_shares
                entry_price = fill_price
                stop_price = pending_stop
                risk = abs(entry_price - stop_price)
                target_price = entry_price + side * params.reward_r * risk
                entry_time = ts
                cash -= commission
                cash += notional if side == -1 else -notional  # short: receive proceeds; long: pay for shares
            pending_entry_side = None
            pending_stop = math.nan

        # 2) Manage an open position: check stop / target / session-end exits.
        if position != 0:
            exit_price = None
            exit_reason = None

            stop_hit = (low[i] <= stop_price) if side == 1 else (high[i] >= stop_price)
            target_hit = False
            if np.isfinite(target_price):
                target_hit = (high[i] >= target_price) if side == 1 else (low[i] <= target_price)

            if stop_hit:
                exit_price, exit_reason = stop_price, "stop"
            elif target_hit:
                exit_price, exit_reason = target_price, "target"
            elif session_end[i]:
                exit_price, exit_reason = close[i], "session_end"

            if exit_price is not None:
                fill_price = _apply_slippage(exit_price, side, entering=False, bps=params.slippage_bps)
                size_shares = abs(position)
                notional = size_shares * fill_price
                commission = notional * params.commission_bps / 1e4
                cash += notional if side == 1 else -notional  # long: sell shares; short: buy back
                cash -= commission

                gross_pnl = side * (fill_price - entry_price) * size_shares
                risk_amount = abs(entry_price - stop_price) * size_shares
                r_multiple = gross_pnl / risk_amount if risk_amount > 0 else np.nan

                trades.append(
                    {
                        "entry_time": entry_time,
                        "exit_time": ts,
                        "side": "long" if side == 1 else "short",
                        "size": size_shares,
                        "entry_price": entry_price,
                        "exit_price": fill_price,
                        "stop_price": stop_price,
                        "target_price": target_price,
                        "exit_reason": exit_reason,
                        "gross_pnl": gross_pnl,
                        "commission": commission,
                        "pnl": gross_pnl - commission,
                        "r_multiple": r_multiple,
                    }
                )

                position = 0.0
                entry_price = stop_price = target_price = math.nan
                entry_time = None
                side = 0

        # 3) If flat, check for a new signal to queue for the next bar's open.
        if position == 0 and pending_entry_side is None and not session_end[i]:
            sig = signal[i]
            if sig == "long":
                pending_entry_side = 1
                pending_stop = stop_price_col[i]
            elif sig == "short" and params.allow_short:
                pending_entry_side = -1
                pending_stop = stop_price_col[i]

        # 4) Mark to market: cash already reflects entry/exit cash flows, so
        # adding the open position's current market value gives equity in
        # both the long and short case (a short position's value is
        # negative, which correctly reduces equity as price rises).
        equity_curve[i] = cash + position * close[i]

    equity_series = pd.Series(equity_curve, index=df.index, name="equity")
    trades_df = pd.DataFrame(trades)
    return trades_df, equity_series
