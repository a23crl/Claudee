# Trial Log

Mandatory record of every variant run, per spec Section 10. Every run of
any variant — including baselines and discarded ones — gets a row here,
whether it came from the Pine indicator's own table or from
`python run_analysis.py`. This log is what the Section 8.8 multiple-testing
haircut counts against (at more than ~20 trials, the validation t-stat bar
rises from 2.0 to 2.5), and the project's hard budget is **40 logged
variants total** (Section 4).

Columns:
- **Sample**: design / validation / holdout.
- **Variant**: only what changed from the primary (Section 3). "Primary"
  means every frozen default, unchanged.
- **Costs stress 1.5x**: avg R with slippage and commission both scaled
  1.5x (Section 8.5's stress test). Fill in once run.
- **Kept?**: yes / no / pending — whether this variant advanced past its
  sample's gate in Section 8.

No rows below have been run yet — this file is the initialized skeleton
required by the deliverables list, not a completed validation. Fill in
Trades/Avg R/Costs-stress/Kept columns as each run actually happens, and do
not backfill numbers without having run the corresponding CSV through
`run_analysis.py` (or read them off the Pine table) first.

| # | Date | Sample | Variant (only what changed) | Trades | Avg R | Costs stress 1.5x | Kept? | Notes |
|---|---|---|---|---|---|---|---|---|
| 1 | | design | Primary (Section 3 defaults) | | | | pending | Required gate: >= 100 trades (Section 8.2) |
| 2 | | design | B0 — no r1 filter, no RVOL filter | | | | pending | N1+N2 baseline |
| 3 | | design | B1 — r1 filter only | | | | pending | N1 test: Primary avg R should exceed this |
| 4 | | design | B2 — RVOL filter only | | | | pending | Diagnostic; not part of the N1/N2 ordering test |
| 5 | | design | B3 — primary, entry direction randomized (Python `analysis.baseline`) | | | | pending | Luck distribution, not a real variant |
| 6 | | design | OR length = 15 (robustness) | | | | pending | One-at-a-time neighbor (Section 8.4) |
| 7 | | design | OR length = 60 (robustness) | | | | pending | One-at-a-time neighbor |
| 8 | | design | RVOL threshold = 1.0 (robustness) | | | | pending | One-at-a-time neighbor |
| 9 | | design | RVOL threshold = 1.5 (robustness) | | | | pending | One-at-a-time neighbor |
| 10 | | design | Stop = OR low (robustness) | | | | pending | One-at-a-time neighbor |
| 11 | | design | Stop = entry - 1.0x ATR(14,D,prior) (robustness) | | | | pending | One-at-a-time neighbor |
| 12 | | design | Target = 1.0R (robustness) | | | | pending | One-at-a-time neighbor |
| 13 | | design | Target = 2.0R (robustness) | | | | pending | One-at-a-time neighbor |
| 14 | | validation | Primary (Section 3 defaults) | | | | pending | Required gates: Section 8.5 (>=60 trades, etc.) |
| 15 | | validation | B0 — no r1 filter, no RVOL filter | | | | pending | Must still be beaten by Primary in validation |
| 16 | | validation | B1 — r1 filter only | | | | pending | Must still be beaten by Primary in validation |
| 17 | | holdout | Primary (frozen candidate, written here BEFORE unlocking) | | | | pending | Touch once, per Section 7.2 / 8.9. Do not fill in before the unlock. |

## Final report (fill in once the protocol in Section 8 completes)

- **Total trials logged:** _(pending)_
- **Primary config (frozen, Section 3):** OR length 30 min · RVOL min 1.2 ·
  RVOL lookback 20 sessions · Stop = OR midpoint · Target = 1.5R · Entry
  cutoff 12:30 ET · Flat time 15:55 ET
- **Holdout result:** _(pending — do not fill in before the holdout row
  above has actually been unlocked and run)_
