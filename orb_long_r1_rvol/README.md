# ORB Long r1+RVOL

A long-only opening-range breakout for MES/MNQ, gated by two filters drawn
from Gao/Han/Li/Zhou-style early-session-continuation research: the sign of
the first-half-hour return (`r1`) and relative volume (`RVOL`) during the
opening range. This is a **prop-firm challenge validation project**, not a
maximize-the-backtest project — see `spec.md` (the frozen spec this repo
implements) for the full rule set, the anti-overfitting rules, and the
validation protocol. Read that file first; this README is only the
mechanical "how do I run this" layer on top of it.

**Everything here is pre-registered.** The rules, the parameter budget (4
parameters, 3 values each, 40-trial budget total), and the validation gates
are frozen in the spec. Do not change thresholds because a chart looks
better with a different number — that is exactly the failure mode the spec
exists to prevent.

## Why two layers (Pine + Python)

TradingView indicators cannot place orders, use `strategy.*` statistics, or
easily do a 10,000-path Monte Carlo. So the work is split:

- **Pine (`orb_long_r1_rvol.pine`)** is the signal, display, and alert
  layer. It simulates its own trades bar-by-bar (since it's an indicator,
  not a strategy), shows a stats table, draws the OR/entry/stop/target
  levels, fires alerts, and exports per-bar data for the Python step.
- **Python (`analysis/`)** cross-checks Pine's own numbers independently,
  runs the paper's r1-continuation regression, and runs the long-history
  validation and prop-firm Monte Carlo that Pine cannot do.

## 1. Load the indicator on TradingView

1. Open the Pine Editor, paste in `orb_long_r1_rvol.pine`, and add it to a
   **1- or 5-minute** chart of `MES1!` (or `MNQ1!`). Any other chart
   timeframe raises a runtime error by design (Section 5 of the spec).
2. Leave every input at its default — those are the frozen Section 3
   values. The dropdowns for OR length, stop mode, RVOL threshold, and
   target R exist only to run the Section 4 robustness variants, not to be
   tuned freely.
3. Set **Design End Date**, **Validation End Date**, and **Holdout Start
   Date** under "Data Splits" once you know how much intraday history your
   plan actually gives you (Section 7.1). If your chart's history doesn't
   reach back before Design End Date, the table shows `INSUFFICIENT
   HISTORY` instead of a misleading number.
4. In "Data Hygiene", list roll days, the day after a roll, holidays, and
   half-days in **Excluded Dates** (comma-separated `YYYY-MM-DD`). These
   days are skipped for trading *and* excluded from the RVOL baseline.
5. Set your firm's actual rules under "Risk / Prop Firm" (account size,
   profit target, trailing drawdown, drawdown type, daily loss limit,
   consistency %) — the on-chart prop-path check and the Python Monte Carlo
   both need these to match.
6. Leave **Unlock Holdout** off until Section 7.2's discipline is satisfied:
   the candidate's exact parameters are written into `trial_log.md` first.
   While off, all holdout-period trades are excluded from every statistic
   and the table shows `HOLDOUT LOCKED`.

## 2. Export the data for Python validation

TradingView's **"Export chart data"** (the icon in the chart toolbar, or
the Pine data window's own export) writes one row per bar, with the
indicator's `display.data_window` plots as columns: `r1`, `rvol`, `orHi`,
`orLo`, `sigFlag`, `entryFill`, `stopPx`, `targetPx`, `exitPx`, `netR`,
`contracts`, `isExcludedDay`, `sampleId`, `eventFlag`, alongside the usual
`time`/`open`/`high`/`low`/`close`/`volume` columns. Most of these columns
are blank except on the one bar the event happened on (Section 6.3) — that
sparsity is what lets the CSV be filtered down to one line per trade.

`eventFlag` codes: `1` = signal, `2` = entry fill, `3` = stop exit, `4` =
target exit, `5` = time exit, `6` = skipped (sizing rounded below 1
contract).

## 3. Run the Python analysis

```bash
pip install -r requirements.txt
python run_analysis.py --csv path/to/export.csv --risk-per-trade 200 \
    --account-size 50000 --profit-target 3000 --trailing-dd 2000 \
    --dd-type EOD --daily-loss-limit 1000 --consistency-pct 30
```

This runs the Section 9 pipeline in order:

1. **Cross-check** — recomputes trades/win-rate/avg-R/payoff/profit-factor/
   max-losing-streak/max-drawdown-R/skipped-count per sample, independently
   of Pine. These must match the Pine table to within rounding; if they
   don't, the Pine logic (or this recompute) has a bug, not a finding.
2. **r1 regression by year** — the paper's own test: does `r1` predict the
   10:00-to-close return? Run on every RTH session in the export, not just
   traded days.
3. **Bucketed diagnostics** — expectancy by RVOL bucket (useful for the N2
   test — what did the RVOL filter actually remove?), by year (single-year
   dependence check, Section 8.7), by day of week, by exit type.
4. **B3 baseline + permutation test** — randomizes trade direction as a
   luck distribution, and a sign-flip permutation test on the primary's
   mean R.
5. **Prop-challenge Monte Carlo** — block-bootstraps the trade P&L series
   (each trade is already one trading day's outcome, since the strategy
   takes at most one trade/day) and simulates sequential attempts against
   your firm's rules: pass rate, breach rate, median days to pass, worst
   losing streak, 5th-percentile equity path.
6. **Risk-per-trade sweep** — the fixed grid from Section 9.6 (5% / 10% /
   15% / 20% of the drawdown buffer), compared by pass rate vs. breach
   rate, never by mean return.

Pass `--include-holdout` only after flipping `Unlock Holdout` on in Pine
*and* writing the frozen candidate into `trial_log.md` first — never before.

## 4. Run the tests

```bash
pytest tests/ -v
```

Covers: hand-computed stats arithmetic (win rate, payoff, profit factor,
max losing streak, max drawdown in R, skip counting), the CSV-export
round-trip (entry/exit pairing, rvol forward-fill, sample-id gap handling),
the r1-regression slope recovery on a planted synthetic relationship, the
permutation test's behavior on pure noise vs. a real edge, and four
Monte Carlo sanity checks (guaranteed-win path never breaches, a large loss
breaches the trailing drawdown immediately, the daily loss limit can fire
before the drawdown does, and the consistency rule blocks a pass dominated
by one outsized day).

## The unlock procedure (read before touching the holdout switch)

1. Finish Sections 8.1-8.8 of the spec on **design and validation only**.
2. Write the frozen candidate's exact parameter values into `trial_log.md`.
3. Flip **Unlock Holdout** on in the Pine indicator.
4. Re-export the CSV and re-run `run_analysis.py --include-holdout`.
5. The Pine table now prints `HOLDOUT VIEWED - no further tuning allowed`
   permanently. A holdout failure rejects the strategy — the only allowed
   reaction is a new hypothesis on new data, not a re-tune (Section 8.9).

## Project layout

```
orb_long_r1_rvol.pine   # the indicator (Pine v6)
analysis/
  io.py            # load the exported CSV, reconstruct trades, split by sample
  stats.py         # recompute + cross-check Pine's own per-sample stats
  regression.py    # r1 -> 10:00-to-close return regression, by year
  buckets.py       # RVOL bucket / year / day-of-week / exit-type diagnostics
  baseline.py      # B3 randomized-direction baseline + permutation test
  montecarlo.py    # prop-challenge block-bootstrap Monte Carlo
  risk_sweep.py    # risk-per-trade sweep over the fixed 5/10/15/20% grid
  cli.py           # orchestrates the Section 9 pipeline end to end
run_analysis.py    # CLI entry point
tests/             # pytest unit tests
trial_log.md       # mandatory record of every variant run (Section 10)
```

## Known Pine v6 / TradingView limitations

- TradingView's intraday history depth is plan-dependent and is usually
  much shorter than the spec's ideal 2010-onward design/validation/holdout
  split — hence the date-input splits plus the `INSUFFICIENT HISTORY`
  guard rather than hardcoded date ranges.
- The prop-rule path check on the Pine side (Section 7.3) is a light,
  trade-granularity approximation: it can only observe P&L at trade exits,
  so "Intraday" trailing drawdown is approximated using the running
  trade-by-trade equity rather than true tick-by-tick intrabar equity. The
  Python Monte Carlo carries the same limitation for the same reason
  (Section 9.5's docstring notes it) — since the strategy takes at most one
  trade per day, a day's P&L and a trade's P&L are the same number either
  way, so this is a description of the true output resolution, not an
  approximation Python could remove.
- Pine has no `while` loop; the drawing-object pruning (`f_pruneBoxes` /
  `f_pruneLines` / `f_pruneLabels`) uses bounded `for` loops instead, and is
  duplicated per drawing type because Pine's box/line/label deletion calls
  are type-specific (a single generic prune function can't call the right
  `*.delete()`).
- `array.from()`, `switch` as a statement, and tuple returns from
  user-defined functions (used throughout the stats engine) are all
  Pine v5+/v6 features relied on here; nothing in this script is
  intentionally v5-only syntax.
