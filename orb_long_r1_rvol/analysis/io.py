"""Load TradingView's "Export chart data" CSV and reconstruct the trade log.

The Pine indicator plots one row of data per bar with `display.data_window`
(Section 6.3): r1, rvol, orHi, orLo, sigFlag, entryFill, stopPx, targetPx,
exitPx, netR, contracts, isExcludedDay, sampleId, eventFlag. Most columns
are NaN except on the bar the event happened on, so a trade is reconstructed
by pairing an eventFlag==2 (entry fill) row with the next eventFlag in
{3, 4, 5} (stop / target / time exit), or a standalone eventFlag==6 row
(skipped, sizing too small).
"""

from __future__ import annotations

import pandas as pd

EXIT_TYPE_BY_FLAG = {3: "stop", 4: "target", 5: "time"}

# r1 / rvol / orHi / orLo are only written on the bar the OR ends; forward-fill
# them within the session so a later entry-fill row can see that day's values.
_FFILL_COLS = ["r1", "rvol", "orHi", "orLo"]


def load_bars(csv_path: str) -> pd.DataFrame:
    """Load the raw exported CSV into a DataFrame indexed by bar time."""
    df = pd.read_csv(csv_path)
    df.columns = [c.strip() for c in df.columns]

    time_col = next((c for c in df.columns if c.lower() in ("time", "date", "time (utc)")), df.columns[0])
    df = df.rename(columns={time_col: "time"})
    df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
    df = df.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)

    for col in _FFILL_COLS:
        if col in df.columns:
            df[col] = df[col].ffill()

    return df


def extract_trades(bars: pd.DataFrame) -> pd.DataFrame:
    """Pair entry/exit event rows into one row per simulated trade."""
    if "eventFlag" not in bars.columns:
        raise ValueError("CSV has no 'eventFlag' column — was it exported with the indicator's data-window plots on?")

    events = bars.dropna(subset=["eventFlag"]).sort_values("time")
    trades: list[dict] = []
    pending: pd.Series | None = None

    for _, row in events.iterrows():
        flag = int(row["eventFlag"])
        if flag == 2:  # entry fill
            pending = row
        elif flag in EXIT_TYPE_BY_FLAG:
            trades.append(
                {
                    "entry_time": pending["time"] if pending is not None else pd.NaT,
                    "exit_time": row["time"],
                    "entry_fill": pending["entryFill"] if pending is not None else float("nan"),
                    "stop_px": pending["stopPx"] if pending is not None else float("nan"),
                    "target_px": pending["targetPx"] if pending is not None else float("nan"),
                    "rvol": pending["rvol"] if pending is not None else float("nan"),
                    "exit_px": row["exitPx"],
                    "net_r": row["netR"],
                    "contracts": row.get("contracts", float("nan")),
                    "sample_id": row["sampleId"],
                    "exit_type": EXIT_TYPE_BY_FLAG[flag],
                    "skipped": False,
                }
            )
            pending = None
        elif flag == 6:  # skipped: sizing rounded below 1 contract
            trades.append(
                {
                    "entry_time": row["time"],
                    "exit_time": pd.NaT,
                    "entry_fill": float("nan"),
                    "stop_px": float("nan"),
                    "target_px": float("nan"),
                    "rvol": row.get("rvol", float("nan")),
                    "exit_px": float("nan"),
                    "net_r": float("nan"),
                    "contracts": 0,
                    "sample_id": row["sampleId"],
                    "exit_type": "skipped",
                    "skipped": True,
                }
            )
            pending = None

    return pd.DataFrame(trades)


def split_by_sample(trades: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Split into design (0) / validation (1) / holdout (2). sampleId 3 (the
    gap between validation end and holdout start, Section 7.1) is dropped."""
    return {
        "design": trades[trades["sample_id"] == 0].reset_index(drop=True),
        "validation": trades[trades["sample_id"] == 1].reset_index(drop=True),
        "holdout": trades[trades["sample_id"] == 2].reset_index(drop=True),
    }
