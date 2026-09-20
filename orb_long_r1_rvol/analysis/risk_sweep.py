"""Risk-per-trade sweep over the fixed grid in Section 9.6: 5% / 10% / 15% /
20% of the trailing-drawdown buffer. Choose by pass rate vs. breach rate,
never by mean return — a higher-risk cell always shows a bigger mean return
and that alone says nothing about challenge survivability.
"""

from __future__ import annotations

import numpy as np

from . import montecarlo

BUFFER_FRACTIONS = (0.05, 0.10, 0.15, 0.20)


def risk_per_trade_sweep(
    net_r: np.ndarray,
    account_size: float,
    profit_target: float,
    trailing_dd: float,
    dd_type: str,
    daily_loss_limit: float,
    consistency_pct: float,
    n_paths: int = 10000,
    seed: int | None = None,
) -> list[dict]:
    r_multiples = np.asarray(net_r, dtype=float)
    rows = []
    for frac in BUFFER_FRACTIONS:
        risk_usd = frac * trailing_dd
        daily_pnls = r_multiples * risk_usd
        mc = montecarlo.prop_monte_carlo(
            daily_pnls,
            account_size=account_size,
            profit_target=profit_target,
            trailing_dd=trailing_dd,
            dd_type=dd_type,
            daily_loss_limit=daily_loss_limit,
            consistency_pct=consistency_pct,
            n_paths=n_paths,
            seed=seed,
        )
        rows.append(
            {
                "risk_fraction_of_buffer": frac,
                "risk_usd": risk_usd,
                "pass_rate": mc["pass_rate"],
                "breach_rate": mc["breach_rate"],
                "median_days_to_pass": mc["median_days_to_pass"],
                "worst_case_losing_streak": mc["worst_case_losing_streak"],
            }
        )
    return rows
