import numpy as np
import pandas as pd
import pytest

from vwap_pullback.backtest import BacktestParams, run_backtest


def _base_df(rows, start="2024-01-01 09:30", freq_minutes=1):
    """rows: list of dicts with open/high/low/close/signal/stop_price/session_end."""
    index = pd.date_range(start, periods=len(rows), freq=f"{freq_minutes}min")
    df = pd.DataFrame(rows, index=index)
    return df


def test_long_trade_hits_target_next_bar_open_entry_no_costs():
    rows = [
        {"open": 100, "high": 101, "low": 99, "close": 100, "signal": "long", "stop_price": 98, "session_end": False},
        {"open": 100, "high": 105, "low": 99.5, "close": 104, "signal": None, "stop_price": np.nan, "session_end": False},
        {"open": 104, "high": 106, "low": 103, "close": 105, "signal": None, "stop_price": np.nan, "session_end": True},
    ]
    df = _base_df(rows)
    params = BacktestParams(
        initial_cash=100_000, risk_pct=0.01, reward_r=2.0, commission_bps=0, slippage_bps=0
    )
    trades, equity = run_backtest(df, params)

    assert len(trades) == 1
    t = trades.iloc[0]
    # dollar_risk = 100_000 * 0.01 = 1000; entry fill = bar1 open = 100; risk/share = |100-98| = 2
    # size = 1000 / 2 = 500 shares; target = 100 + 2*2 = 104; bar1 high (105) >= 104 -> target hit same bar
    assert t["side"] == "long"
    assert t["size"] == 500
    assert t["entry_price"] == pytest.approx(100.0)
    assert t["exit_price"] == pytest.approx(104.0)
    assert t["exit_reason"] == "target"
    assert t["gross_pnl"] == pytest.approx((104 - 100) * 500)
    assert t["r_multiple"] == pytest.approx(2.0)
    assert t["pnl"] == pytest.approx(t["gross_pnl"])  # zero commission
    # equity after exit = cash: 100_000 - 500*100 (buy) + 500*104 (sell) = 102_000
    assert equity.iloc[1] == pytest.approx(102_000.0)


def test_short_trade_hits_stop_with_commission_and_slippage():
    rows = [
        {"open": 50, "high": 50.5, "low": 49.5, "close": 50, "signal": "short", "stop_price": 52, "session_end": False},
        {"open": 50, "high": 53, "low": 49, "close": 52.5, "signal": None, "stop_price": np.nan, "session_end": True},
    ]
    df = _base_df(rows)
    params = BacktestParams(
        initial_cash=100_000, risk_pct=0.02, reward_r=2.0, commission_bps=10, slippage_bps=20, allow_short=True
    )
    trades, equity = run_backtest(df, params)

    assert len(trades) == 1
    t = trades.iloc[0]
    # entry: raw open=50, short slippage makes fill worse (lower) by 20bps -> 50*(1-0.002)=49.9
    entry_fill = 50 * (1 - 20 / 1e4)
    assert t["entry_price"] == pytest.approx(entry_fill)
    risk_per_share = abs(entry_fill - 52)
    dollar_risk = 100_000 * 0.02
    expected_size = int(dollar_risk / risk_per_share)
    assert t["size"] == expected_size
    # stop hit: bar1 high (53) >= stop(52); exit slippage on a short exit (buy back) is adverse -> higher
    exit_fill = 52 * (1 + 20 / 1e4)
    assert t["exit_price"] == pytest.approx(exit_fill)
    assert t["exit_reason"] == "stop"
    assert t["gross_pnl"] == pytest.approx(-1 * (exit_fill - entry_fill) * expected_size)
    assert t["commission"] > 0
    assert t["pnl"] == pytest.approx(t["gross_pnl"] - t["commission"])


def test_forced_flat_at_session_end():
    rows = [
        {"open": 100, "high": 101, "low": 99, "close": 100, "signal": "long", "stop_price": 90, "session_end": False},
        {"open": 100, "high": 100.5, "low": 99.8, "close": 100.2, "signal": None, "stop_price": np.nan, "session_end": True},
    ]
    df = _base_df(rows)
    params = BacktestParams(initial_cash=100_000, risk_pct=0.01, commission_bps=0, slippage_bps=0)
    trades, equity = run_backtest(df, params)

    assert len(trades) == 1
    assert trades.iloc[0]["exit_reason"] == "session_end"
    assert trades.iloc[0]["exit_price"] == pytest.approx(100.2)  # exits at close, not open


def test_no_entry_on_last_bar_of_session():
    rows = [
        {"open": 100, "high": 101, "low": 99, "close": 100, "signal": "long", "stop_price": 98, "session_end": True},
    ]
    df = _base_df(rows)
    trades, equity = run_backtest(df, BacktestParams())
    assert len(trades) == 0


def test_short_disabled_when_allow_short_false():
    rows = [
        {"open": 100, "high": 101, "low": 99, "close": 100, "signal": "short", "stop_price": 102, "session_end": False},
        {"open": 100, "high": 101, "low": 99, "close": 100, "signal": None, "stop_price": np.nan, "session_end": True},
    ]
    df = _base_df(rows)
    trades, _ = run_backtest(df, BacktestParams(allow_short=False))
    assert len(trades) == 0
