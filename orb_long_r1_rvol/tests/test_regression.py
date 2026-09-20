import numpy as np
import pandas as pd

from analysis import regression


def _make_bars_for_days(n_days, r1_to_later_slope, seed=0):
    """One synthetic RTH session per day: a 9:30 bar, a bar just before 10:00
    (carries r1) at some random offset, and a 15:59 close. later_return is
    built to depend linearly on r1 plus noise, so the fitted slope should
    recover something close to `r1_to_later_slope`.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for d in range(n_days):
        date = pd.Timestamp("2024-01-02") + pd.Timedelta(days=d)
        r1 = rng.normal(0, 0.01)
        pre10_close = 100.0
        later_return = r1_to_later_slope * r1 + rng.normal(0, 0.0005)
        post10_close = pre10_close * (1 + later_return)

        rows.append(dict(time=date + pd.Timedelta(hours=9, minutes=30), close=pre10_close - 0.1, r1=None))
        rows.append(dict(time=date + pd.Timedelta(hours=9, minutes=59), close=pre10_close, r1=r1))
        rows.append(dict(time=date + pd.Timedelta(hours=15, minutes=59), close=post10_close, r1=None))
    df = pd.DataFrame(rows)
    df["time"] = pd.to_datetime(df["time"]).dt.tz_localize("America/New_York")
    return df


def test_build_daily_returns_one_row_per_session():
    bars = _make_bars_for_days(10, r1_to_later_slope=1.0)
    daily = regression.build_daily_returns(bars)
    assert len(daily) == 10
    assert set(daily.columns) >= {"date", "year", "r1", "later_return"}


def test_regression_recovers_a_strong_planted_slope():
    bars = _make_bars_for_days(60, r1_to_later_slope=2.0, seed=1)
    daily = regression.build_daily_returns(bars)
    daily["year"] = 2024  # force everything into one year for this check
    fit = regression.regression_by_year(daily)
    assert len(fit) == 1
    assert abs(fit.loc[0, "slope"] - 2.0) < 0.5


def test_regression_reports_nan_for_years_with_too_few_sessions():
    bars = _make_bars_for_days(3, r1_to_later_slope=1.0, seed=2)
    daily = regression.build_daily_returns(bars)
    fit = regression.regression_by_year(daily, min_obs=5)
    assert fit.loc[0, "n"] == 3
    assert np.isnan(fit.loc[0, "slope"])
