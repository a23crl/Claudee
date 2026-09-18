"""Performance metrics for a backtest's trade list and equity curve."""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252


def _infer_bars_per_year(equity_curve: pd.Series) -> float:
    if len(equity_curve) < 2:
        return TRADING_DAYS_PER_YEAR
    n_days = max((equity_curve.index[-1] - equity_curve.index[0]).days, 1)
    bars_per_day = len(equity_curve) / n_days * (7 / 5)  # rough trading-day adjustment
    return max(bars_per_day * TRADING_DAYS_PER_YEAR, 1.0)


def max_drawdown(equity_curve: pd.Series) -> tuple[float, pd.Timedelta]:
    running_max = equity_curve.cummax()
    drawdown = equity_curve / running_max - 1.0
    max_dd = drawdown.min()

    trough_idx = drawdown.idxmin()
    peak_idx = equity_curve.loc[:trough_idx].idxmax()
    recovery = equity_curve.loc[trough_idx:]
    recovered = recovery[recovery >= equity_curve.loc[peak_idx]]
    end_idx = recovered.index[0] if len(recovered) else equity_curve.index[-1]
    duration = end_idx - peak_idx
    return float(max_dd), duration


def compute_metrics(trades: pd.DataFrame, equity_curve: pd.Series, initial_cash: float) -> dict:
    bar_returns = equity_curve.pct_change().dropna()
    bars_per_year = _infer_bars_per_year(equity_curve)

    total_return = equity_curve.iloc[-1] / initial_cash - 1.0 if len(equity_curve) else 0.0
    n_years = max((equity_curve.index[-1] - equity_curve.index[0]).days, 1) / 365.25 if len(equity_curve) else 1
    cagr = (equity_curve.iloc[-1] / initial_cash) ** (1 / n_years) - 1.0 if len(equity_curve) and n_years > 0 else 0.0

    vol_annualized = bar_returns.std() * np.sqrt(bars_per_year) if len(bar_returns) else np.nan
    sharpe = (bar_returns.mean() * bars_per_year) / vol_annualized if vol_annualized and vol_annualized > 0 else np.nan

    downside = bar_returns[bar_returns < 0]
    downside_vol = downside.std() * np.sqrt(bars_per_year) if len(downside) else np.nan
    sortino = (
        (bar_returns.mean() * bars_per_year) / downside_vol
        if downside_vol and downside_vol > 0
        else np.nan
    )

    max_dd, max_dd_duration = max_drawdown(equity_curve) if len(equity_curve) else (np.nan, pd.Timedelta(0))

    n_trades = len(trades)
    if n_trades:
        wins = trades[trades["pnl"] > 0]
        losses = trades[trades["pnl"] <= 0]
        win_rate = len(wins) / n_trades
        gross_profit = wins["pnl"].sum()
        gross_loss = -losses["pnl"].sum()
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else np.inf
        avg_win = wins["pnl"].mean() if len(wins) else 0.0
        avg_loss = losses["pnl"].mean() if len(losses) else 0.0
        avg_r = trades["r_multiple"].mean()
        expectancy_r = avg_r
    else:
        win_rate = profit_factor = avg_win = avg_loss = avg_r = expectancy_r = np.nan

    return {
        "total_return_pct": total_return * 100,
        "cagr_pct": cagr * 100,
        "annualized_vol_pct": vol_annualized * 100 if pd.notna(vol_annualized) else np.nan,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown_pct": max_dd * 100,
        "max_drawdown_duration_days": max_dd_duration.days if len(equity_curve) else np.nan,
        "num_trades": n_trades,
        "win_rate_pct": win_rate * 100 if pd.notna(win_rate) else np.nan,
        "profit_factor": profit_factor,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "avg_r_multiple": avg_r,
        "expectancy_r": expectancy_r,
        "final_equity": equity_curve.iloc[-1] if len(equity_curve) else initial_cash,
    }


def format_report(metrics: dict) -> str:
    lines = ["=" * 50, "VWAP PULLBACK — BACKTEST REPORT", "=" * 50]
    fmt = {
        "total_return_pct": ("Total return", "{:.2f}%"),
        "cagr_pct": ("CAGR", "{:.2f}%"),
        "annualized_vol_pct": ("Annualized vol", "{:.2f}%"),
        "sharpe": ("Sharpe", "{:.2f}"),
        "sortino": ("Sortino", "{:.2f}"),
        "max_drawdown_pct": ("Max drawdown", "{:.2f}%"),
        "max_drawdown_duration_days": ("Max DD duration (days)", "{:.0f}"),
        "num_trades": ("Number of trades", "{:.0f}"),
        "win_rate_pct": ("Win rate", "{:.2f}%"),
        "profit_factor": ("Profit factor", "{:.2f}"),
        "avg_win": ("Avg win ($)", "{:.2f}"),
        "avg_loss": ("Avg loss ($)", "{:.2f}"),
        "avg_r_multiple": ("Avg R multiple", "{:.2f}"),
        "expectancy_r": ("Expectancy (R)", "{:.2f}"),
        "final_equity": ("Final equity ($)", "{:.2f}"),
    }
    for key, (label, fstring) in fmt.items():
        value = metrics.get(key, np.nan)
        value_str = fstring.format(value) if pd.notna(value) else "n/a"
        lines.append(f"{label:<28} {value_str:>12}")
    lines.append("=" * 50)
    return "\n".join(lines)
