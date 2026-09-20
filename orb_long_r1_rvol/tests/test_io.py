import pandas as pd

from analysis import io


def _write_export_csv(path):
    """Mimic TradingView's exported chart-data CSV for one signal day and one
    skipped day: OR ends and sets r1/rvol (eventFlag NaN on that bar in this
    minimal fixture), then a signal bar, an entry-fill bar, and a stop-exit
    bar; then a second day with a skipped (too-small sizing) entry.
    """
    rows = [
        # day 1: OR just ended -- r1/rvol get written here, no event yet
        dict(time="2024-01-02T14:00:00Z", close=100.0, r1=0.001, rvol=1.4, orHi=100.5, orLo=99.5,
             sigFlag=None, entryFill=None, stopPx=None, targetPx=None, exitPx=None, netR=None,
             contracts=None, isExcludedDay=0, sampleId=None, eventFlag=None),
        # signal bar
        dict(time="2024-01-02T14:05:00Z", close=100.6, r1=None, rvol=None, orHi=None, orLo=None,
             sigFlag=1, entryFill=None, stopPx=None, targetPx=None, exitPx=None, netR=None,
             contracts=None, isExcludedDay=None, sampleId=None, eventFlag=1),
        # entry fill bar (next bar's open)
        dict(time="2024-01-02T14:06:00Z", close=100.7, r1=None, rvol=None, orHi=None, orLo=None,
             sigFlag=None, entryFill=100.65, stopPx=100.0, targetPx=101.6, exitPx=None, netR=None,
             contracts=2, isExcludedDay=None, sampleId=None, eventFlag=2),
        # stop-exit bar
        dict(time="2024-01-02T15:00:00Z", close=99.9, r1=None, rvol=None, orHi=None, orLo=None,
             sigFlag=None, entryFill=None, stopPx=None, targetPx=None, exitPx=99.95, netR=-1.02,
             contracts=None, isExcludedDay=None, sampleId=0, eventFlag=3),
        # day 2: a skipped trade (sizing rounded below 1 contract)
        dict(time="2024-01-03T14:06:00Z", close=50.0, r1=None, rvol=1.1, orHi=None, orLo=None,
             sigFlag=None, entryFill=None, stopPx=None, targetPx=None, exitPx=None, netR=None,
             contracts=0, isExcludedDay=None, sampleId=0, eventFlag=6),
    ]
    df = pd.DataFrame(rows)
    df.to_csv(path, index=False)


def test_load_and_extract_round_trip(tmp_path):
    csv_path = tmp_path / "export.csv"
    _write_export_csv(csv_path)

    bars = io.load_bars(str(csv_path))
    trades = io.extract_trades(bars)

    assert len(trades) == 2

    executed = trades[~trades["skipped"]].iloc[0]
    assert executed["entry_fill"] == 100.65
    assert executed["stop_px"] == 100.0
    assert executed["exit_type"] == "stop"
    assert executed["net_r"] == -1.02
    assert executed["sample_id"] == 0
    # rvol is only written at the OR-end bar; forward-fill should carry the
    # day's value through to the entry-fill bar
    assert executed["rvol"] == 1.4

    skipped = trades[trades["skipped"]].iloc[0]
    assert skipped["exit_type"] == "skipped"
    assert pd.isna(skipped["net_r"])


def test_split_by_sample_drops_the_gap_bucket():
    trades = pd.DataFrame({"sample_id": [0, 1, 2, 3, 0]})
    split = io.split_by_sample(trades)
    assert len(split["design"]) == 2
    assert len(split["validation"]) == 1
    assert len(split["holdout"]) == 1
    total_kept = sum(len(v) for v in split.values())
    assert total_kept == 4  # the sampleId==3 "gap" row is dropped
