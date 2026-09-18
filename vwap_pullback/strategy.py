"""VWAP Pullback strategy: signal generation.

Idea: on an intraday chart, session VWAP acts as a dynamic reference level
that institutional flow tends to defend. This strategy trades *with* the
prevailing intraday trend: once price has extended away from VWAP by a
meaningful amount (establishing a directional bias), wait for it to pull
back toward VWAP, then enter on a confirmation bar that shows the pullback
failing and price resuming in the original trend direction.

Long setup:
  1. Price extends >= min_extension_atr (in ATR units) above VWAP -> bullish bias.
  2. Bias must hold for >= min_trend_bars bars (no opposite extension in between).
  3. Price pulls back to within pullback_atr_mult ATR of VWAP.
  4. Trigger bar: closes back above VWAP, is a bullish bar (close > open), and
     (optionally) breaks above the prior bar's high -> enter long next bar open.

Short setup is the mirror image.

Risk management:
  - Stop loss at the pullback's swing low/high (over stop_lookback bars) with
    a small ATR buffer.
  - Take profit at reward_r multiples of the initial risk (R).
  - Forced flat exit at the last bar of the session (no overnight risk, and
    VWAP itself resets each session so the reference level becomes stale).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from vwap_pullback.indicators import atr as compute_atr
from vwap_pullback.indicators import session_vwap


@dataclass(frozen=True)
class VWAPPullbackParams:
    atr_period: int = 14
    min_extension_atr: float = 1.0   # how far price must extend from VWAP to establish bias
    min_trend_bars: int = 3          # bias must hold this many bars before a pullback trade is valid
    pullback_atr_mult: float = 0.35  # "close enough to VWAP" zone, in ATR units
    require_momentum_break: bool = True  # trigger bar must also break prior bar's high/low
    stop_lookback: int = 5           # bars used to find the pullback swing low/high for the stop
    stop_buffer_atr: float = 0.1     # extra buffer beyond the swing low/high, in ATR units
    reward_r: float = 2.0            # take-profit distance as a multiple of initial risk (R)
    min_atr_value: float = 1e-6      # guards against division issues on dead/no-volume bars


def generate_signals(df: pd.DataFrame, params: VWAPPullbackParams = VWAPPullbackParams()) -> pd.DataFrame:
    """Compute VWAP/ATR context and entry signals.

    Returns a copy of df with added columns: vwap, atr, dist_atr, signal
    ("long"/"short"/None), stop_price, session_end (bool: last bar of its
    session). `signal` marks the bar whose CLOSE triggered the setup; the
    backtester is responsible for filling at the *next* bar's open to avoid
    lookahead bias.
    """
    out = df.copy()
    out["vwap"] = session_vwap(out)
    out["atr"] = compute_atr(out, params.atr_period).clip(lower=params.min_atr_value)
    out["dist_atr"] = (out["close"] - out["vwap"]) / out["atr"]

    session_id = out.index.date
    session_end = pd.Series(session_id, index=out.index) != pd.Series(session_id, index=out.index).shift(-1)
    session_end.iloc[-1] = True
    out["session_end"] = session_end

    close = out["close"].to_numpy()
    open_ = out["open"].to_numpy()
    high = out["high"].to_numpy()
    low = out["low"].to_numpy()
    atr_arr = out["atr"].to_numpy()
    dist_arr = out["dist_atr"].to_numpy()
    vwap_arr = out["vwap"].to_numpy()
    session_arr = np.asarray(session_id)

    n = len(out)
    signals = np.array([None] * n, dtype=object)
    stop_prices = np.full(n, np.nan)

    bias = None
    bias_bar_count = 0
    extension_seen = False

    for i in range(n):
        if i == 0 or session_arr[i] != session_arr[i - 1]:
            bias = None
            bias_bar_count = 0
            extension_seen = False

        d = dist_arr[i]
        if np.isnan(d):
            continue

        if bias is None:
            if d >= params.min_extension_atr:
                bias, extension_seen, bias_bar_count = "up", True, 1
            elif d <= -params.min_extension_atr:
                bias, extension_seen, bias_bar_count = "down", True, 1
            continue

        if bias == "up" and d <= -params.min_extension_atr:
            bias, extension_seen, bias_bar_count = "down", True, 1
            continue
        if bias == "down" and d >= params.min_extension_atr:
            bias, extension_seen, bias_bar_count = "up", True, 1
            continue

        bias_bar_count += 1
        if bias == "up" and d >= params.min_extension_atr:
            extension_seen = True
        elif bias == "down" and d <= -params.min_extension_atr:
            extension_seen = True

        armed = extension_seen and bias_bar_count >= params.min_trend_bars and abs(d) <= params.pullback_atr_mult
        if not armed or i == 0:
            continue

        if bias == "up":
            bullish_bar = close[i] > open_[i]
            reclaimed = close[i] > vwap_arr[i]
            momentum_ok = (close[i] > high[i - 1]) if params.require_momentum_break else True
            if bullish_bar and reclaimed and momentum_ok:
                lookback_start = max(0, i - params.stop_lookback + 1)
                swing_low = low[lookback_start : i + 1].min()
                signals[i] = "long"
                stop_prices[i] = swing_low - params.stop_buffer_atr * atr_arr[i]
                extension_seen = False
        else:
            bearish_bar = close[i] < open_[i]
            reclaimed = close[i] < vwap_arr[i]
            momentum_ok = (close[i] < low[i - 1]) if params.require_momentum_break else True
            if bearish_bar and reclaimed and momentum_ok:
                lookback_start = max(0, i - params.stop_lookback + 1)
                swing_high = high[lookback_start : i + 1].max()
                signals[i] = "short"
                stop_prices[i] = swing_high + params.stop_buffer_atr * atr_arr[i]
                extension_seen = False

    out["signal"] = signals
    out["stop_price"] = stop_prices
    return out
