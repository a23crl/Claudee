import numpy as np
import pandas as pd

from vwap_pullback.strategy import VWAPPullbackParams, generate_signals


def _make_session(closes, base_range=1.5, start="2024-01-01 09:30", freq_minutes=1, volume=1000.0):
    """Build a single-session OHLCV frame from a list of closes.

    open[i] = close[i-1] (close[0] a touch below closes[0]); high/low pad
    each bar by base_range so ATR stays large enough that a pullback zone
    defined in ATR units corresponds to a comfortably wide price band.
    """
    n = len(closes)
    index = pd.date_range(start, periods=n, freq=f"{freq_minutes}min")
    opens = [closes[0] - base_range] + list(closes[:-1])
    highs = [max(o, c) + base_range for o, c in zip(opens, closes)]
    lows = [min(o, c) - base_range for o, c in zip(opens, closes)]
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": [volume] * n},
        index=index,
    )


def test_long_signal_fires_after_uptrend_then_pullback_and_reclaim():
    up_leg = [101, 103, 105, 107, 109, 111, 113]           # establishes bullish bias
    pullback_leg = [111.5, 110, 108.5, 107.2]              # retraces back toward VWAP
    trigger_bar = [113.5]                                  # strong bullish reclaim + momentum break
    closes = up_leg + pullback_leg + trigger_bar
    df = _make_session(closes)

    params = VWAPPullbackParams(
        atr_period=3,
        min_extension_atr=1.0,
        min_trend_bars=2,
        pullback_atr_mult=1.0,
        require_momentum_break=True,
        stop_lookback=3,
    )
    result = generate_signals(df, params)

    signals = result["signal"].dropna()
    assert (signals == "long").any(), f"expected a long signal; got signals={signals.to_dict()}"

    # The stop for any long signal must sit below that bar's low (sane risk placement).
    long_idx = result.index[result["signal"] == "long"]
    for ts in long_idx:
        assert result.loc[ts, "stop_price"] < result.loc[ts, "low"]


def test_short_signal_fires_after_downtrend_then_pullback_and_reclaim():
    down_leg = [99, 97, 95, 93, 91, 89, 87]
    pullback_leg = [88.5, 90, 91.5, 92.8]
    trigger_bar = [86.5]
    closes = down_leg + pullback_leg + trigger_bar
    df = _make_session(closes)

    params = VWAPPullbackParams(
        atr_period=3,
        min_extension_atr=1.0,
        min_trend_bars=2,
        pullback_atr_mult=1.0,
        require_momentum_break=True,
        stop_lookback=3,
    )
    result = generate_signals(df, params)

    signals = result["signal"].dropna()
    assert (signals == "short").any(), f"expected a short signal; got signals={signals.to_dict()}"


def test_no_signal_on_flat_choppy_market():
    rng = np.random.default_rng(0)
    closes = list(100 + rng.normal(0, 0.05, 60))  # tiny noise, no real trend/extension
    df = _make_session(closes, base_range=0.3)

    params = VWAPPullbackParams(min_extension_atr=3.0)  # require a big extension that noise won't produce
    result = generate_signals(df, params)

    assert result["signal"].dropna().empty


def test_signals_reset_at_session_boundary():
    up_leg = [101, 103, 105, 107, 109, 111, 113]
    day1 = _make_session(up_leg, start="2024-01-01 09:30")
    day2 = _make_session([100, 100.2, 99.9], start="2024-01-02 09:30")
    df = pd.concat([day1, day2])

    params = VWAPPullbackParams(atr_period=3, min_extension_atr=1.0, min_trend_bars=2, pullback_atr_mult=1.0)
    result = generate_signals(df, params)

    # Day 2 has no room to build an extension of its own, so it must carry no signal
    # despite day 1 ending in a strong bullish bias.
    day2_signals = result.loc[day2.index, "signal"].dropna()
    assert day2_signals.empty
