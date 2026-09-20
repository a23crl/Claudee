import numpy as np
import pandas as pd

from analysis import baseline


def test_randomize_direction_baseline_excludes_skipped_and_flips_magnitude_not_size():
    trades = pd.DataFrame(
        {
            "net_r": [1.0, -0.5, 2.0, float("nan")],
            "skipped": [False, False, False, True],
        }
    )
    b3 = baseline.randomize_direction_baseline(trades, seed=0)
    assert len(b3) == 3
    assert set(b3["net_r_random_direction"].abs()) == {1.0, 0.5, 2.0}


def test_permutation_test_p_value_is_high_for_pure_noise():
    rng = np.random.default_rng(42)
    noise = pd.Series(rng.normal(0, 1, size=500))
    result = baseline.permutation_test(noise, n_iter=2000, seed=1)
    # a mean drawn from symmetric noise should not look significant
    assert result["p_value"] > 0.05


def test_permutation_test_p_value_is_low_for_a_strong_consistent_edge():
    edge = pd.Series([1.0] * 200)  # every trade wins by the same amount
    result = baseline.permutation_test(edge, n_iter=2000, seed=1)
    assert result["p_value"] < 0.01


def test_t_stat_matches_hand_calculation():
    values = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    expected = values.mean() / (values.std(ddof=1) / np.sqrt(len(values)))
    assert abs(baseline.t_stat(values) - expected) < 1e-9
