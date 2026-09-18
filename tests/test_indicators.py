import numpy as np
import pandas as pd

from vwap_pullback.indicators import session_vwap


def test_session_vwap_matches_manual_calc_and_resets_daily():
    idx = pd.DatetimeIndex(
        [
            "2024-01-01 09:30",
            "2024-01-01 09:35",
            "2024-01-02 09:30",  # new session -> VWAP must reset
        ]
    )
    df = pd.DataFrame(
        {
            "high": [10.0, 12.0, 20.0],
            "low": [8.0, 10.0, 18.0],
            "close": [9.0, 11.0, 19.0],
            "volume": [100.0, 200.0, 50.0],
        },
        index=idx,
    )

    vwap = session_vwap(df)

    tp0 = (10 + 8 + 9) / 3
    assert np.isclose(vwap.iloc[0], tp0)

    tp1 = (12 + 10 + 11) / 3
    expected_bar1 = (tp0 * 100 + tp1 * 200) / (100 + 200)
    assert np.isclose(vwap.iloc[1], expected_bar1)

    # New day: VWAP resets and should equal bar 3's own typical price.
    tp2 = (20 + 18 + 19) / 3
    assert np.isclose(vwap.iloc[2], tp2)
