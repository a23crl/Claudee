import pandas as pd

from analysis import stats


def _trades(rows):
    """rows: list of (net_r, skipped) in chronological order."""
    return pd.DataFrame(
        {
            "exit_time": pd.date_range("2024-01-02", periods=len(rows), freq="1D"),
            "net_r": pd.array([r for r, _ in rows], dtype="float64"),
            "skipped": pd.array([s for _, s in rows], dtype="bool"),
        }
    )


def test_hand_computed_stats():
    # +1.5R, -1R, +1.5R, -1R, -1R  -> 2 wins, 3 losses
    trades = _trades([(1.5, False), (-1.0, False), (1.5, False), (-1.0, False), (-1.0, False)])
    s = stats.compute_stats(trades)

    assert s["trades"] == 5
    assert s["win_rate"] == 40.0
    assert abs(s["avg_r"] - (1.5 + -1.0 + 1.5 + -1.0 + -1.0) / 5) < 1e-9
    # avg win = 1.5, avg loss = 1.0 -> payoff 1.5
    assert abs(s["payoff_ratio"] - 1.5) < 1e-9
    # gross win = 3.0, gross loss = 3.0 -> PF = 1.0
    assert abs(s["profit_factor"] - 1.0) < 1e-9
    # losing streak: the last two losses in a row -> max streak of 2
    assert s["max_losing_streak"] == 2
    assert s["skipped"] == 0


def test_max_drawdown_r_is_worst_peak_to_trough():
    # equity path: 1, 0, -1.5, -0.5, 1.5 -> peak 1 at step1, trough -1.5 at step3 -> DD 2.5
    trades = _trades([(1.0, False), (-1.0, False), (-1.5, False), (1.0, False), (2.0, False)])
    s = stats.compute_stats(trades)
    assert abs(s["max_drawdown_r"] - 2.5) < 1e-9


def test_skipped_trades_counted_but_excluded_from_r_stats():
    trades = _trades([(1.0, False), (float("nan"), True), (-1.0, False)])
    s = stats.compute_stats(trades)
    assert s["trades"] == 2
    assert s["skipped"] == 1
    assert abs(s["avg_r"] - 0.0) < 1e-9


def test_empty_sample_reports_zero_trades_not_an_error():
    s = stats.compute_stats(_trades([]))
    assert s["trades"] == 0
    assert s["skipped"] == 0


def test_cross_check_flags_real_mismatch_and_passes_on_match():
    trades = _trades([(1.5, False), (-1.0, False)])
    recomputed = stats.compute_stats(trades)

    ok = stats.cross_check(recomputed, {"trades": 2, "avg_r": recomputed["avg_r"]})
    assert ok == []

    bad = stats.cross_check(recomputed, {"trades": 3})
    assert len(bad) == 1
    assert "trades" in bad[0]
