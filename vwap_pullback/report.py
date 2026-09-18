"""Plotting helpers: equity curve, drawdown, and price/VWAP with trade markers."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


def plot_equity_curve(equity_curve: pd.Series, out_path: str | Path) -> None:
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.plot(equity_curve.index, equity_curve.values, color="#1f6feb", linewidth=1.2)
    ax.set_title("Equity Curve")
    ax.set_ylabel("Equity ($)")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def plot_drawdown(equity_curve: pd.Series, out_path: str | Path) -> None:
    running_max = equity_curve.cummax()
    drawdown = (equity_curve / running_max - 1.0) * 100
    fig, ax = plt.subplots(figsize=(11, 3))
    ax.fill_between(drawdown.index, drawdown.values, 0, color="#da3633", alpha=0.4)
    ax.plot(drawdown.index, drawdown.values, color="#da3633", linewidth=0.8)
    ax.set_title("Drawdown (%)")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def plot_price_with_trades(
    df: pd.DataFrame,
    trades: pd.DataFrame,
    out_path: str | Path,
    max_bars: int = 2000,
) -> None:
    """Plot close price + VWAP with entry/exit markers, for the last max_bars bars."""
    plot_df = df.iloc[-max_bars:]
    fig, ax = plt.subplots(figsize=(13, 5))
    ax.plot(plot_df.index, plot_df["close"], color="#57606a", linewidth=0.8, label="Close")
    ax.plot(plot_df.index, plot_df["vwap"], color="#8250df", linewidth=1.0, label="VWAP")

    if len(trades):
        window_trades = trades[
            (trades["entry_time"] >= plot_df.index[0]) & (trades["entry_time"] <= plot_df.index[-1])
        ]
        longs = window_trades[window_trades["side"] == "long"]
        shorts = window_trades[window_trades["side"] == "short"]
        ax.scatter(longs["entry_time"], longs["entry_price"], marker="^", color="#1a7f37", s=45, label="Long entry", zorder=5)
        ax.scatter(shorts["entry_time"], shorts["entry_price"], marker="v", color="#da3633", s=45, label="Short entry", zorder=5)
        ax.scatter(window_trades["exit_time"], window_trades["exit_price"], marker="x", color="#333", s=35, label="Exit", zorder=5)

    ax.set_title("Price, VWAP, and Trades")
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def save_all(df: pd.DataFrame, trades: pd.DataFrame, equity_curve: pd.Series, out_dir: str | Path) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    plot_equity_curve(equity_curve, out_dir / "equity_curve.png")
    plot_drawdown(equity_curve, out_dir / "drawdown.png")
    plot_price_with_trades(df, trades, out_dir / "price_trades.png")
    if len(trades):
        trades.to_csv(out_dir / "trades.csv", index=False)
