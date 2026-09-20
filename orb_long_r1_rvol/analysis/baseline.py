"""B3 baseline (randomized entry direction) and a permutation test on the
primary's mean R (Section 4's B3, Section 9.4).

B3 gives a luck distribution: apply the same stops/targets/costs machinery
but flip the trade's direction sign at random, independent of any real
signal. The permutation test asks how often a random sign flip on each
trade would produce a mean R at least as extreme as what was observed —
a cheap, assumption-light significance check that doesn't rely on
normality.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def randomize_direction_baseline(trades: pd.DataFrame, seed: int | None = None) -> pd.DataFrame:
    df = trades[~trades["skipped"]].dropna(subset=["net_r"]).copy()
    rng = np.random.default_rng(seed)
    signs = rng.choice([-1.0, 1.0], size=len(df))
    df["net_r_random_direction"] = df["net_r"] * signs
    return df


def permutation_test(net_r: pd.Series, n_iter: int = 10000, seed: int | None = None) -> dict:
    """Two-sided sign-flip permutation test on the mean of `net_r`."""
    values = net_r.dropna().to_numpy()
    n = len(values)
    if n == 0:
        return {"observed_mean_r": float("nan"), "p_value": float("nan"), "n_iter": n_iter, "n_trades": 0}

    observed = values.mean()
    rng = np.random.default_rng(seed)
    signs = rng.choice([-1.0, 1.0], size=(n_iter, n))
    perm_means = (values[None, :] * signs).mean(axis=1)
    p_value = float(np.mean(np.abs(perm_means) >= abs(observed)))

    return {"observed_mean_r": float(observed), "p_value": p_value, "n_iter": n_iter, "n_trades": n}


def t_stat(net_r: pd.Series) -> float:
    """Section 8.8's multiple-testing haircut needs the t-stat of mean R."""
    values = net_r.dropna().to_numpy()
    n = len(values)
    if n < 2:
        return float("nan")
    se = values.std(ddof=1) / np.sqrt(n)
    if se == 0:
        return float("nan")
    return float(values.mean() / se)
