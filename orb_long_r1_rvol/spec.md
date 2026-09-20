# Spec: Long-Only Opening Range Breakout with First-Half-Hour + Relative-Volume Filter

**Target platform:** TradingView, Pine Script **v6 indicators** (not strategies)
**Instruments:** MES first, MNQ second (RTH signals, 1-minute chart preferred, 5-minute allowed)
**Purpose:** Prop-firm challenge validation. The goal is a *robust, low-parameter* rule with defined risk, not the best backtest curve.

This is the frozen spec this project implements. Do not edit it to match
whatever the code currently does — if the code and this file disagree, the
code is wrong (or ground rule 1 below applies and the mismatch should be
raised, not silently resolved).

---

## 0. Ground rules for Claude Code (read first)

1. **Do not add parameters, filters, or exits that are not in this document.** Every extra knob is a degree of freedom for overfitting. If you think something is missing, list it under "Proposed additions" in your reply and wait.
2. **Frozen defaults are pre-registered.** Section 3 defines the primary configuration. It was chosen from the hypothesis and the source paper's logic, *not* from testing. Do not change defaults based on how they look on the chart.
3. **No look-ahead, no repainting.** Signals use only completed bars. Simulated fills occur at the *next* bar's open. Section 6 lists the exact Pine patterns to use.
4. **Costs are always on.** There is no "gross" mode in any displayed statistic.
5. **The holdout period is masked by default** (Section 7). The indicator must not display holdout statistics unless the user flips an explicit unlock input.

---

## 1. Hypothesis (pre-registered)

**H1 (from Gao, Han, Li, Zhou):** Direction established early in the session (previous close to 10:00 ET) tends to continue later in the day.
**H2 (mechanism):** The continuation is stronger when early-session participation is high (informed/hedging flow), so a relative-volume filter should *raise expectancy per trade* on top of H1.
**Null hypotheses we try to reject:**
- N1: The r1 > 0 filter adds nothing versus the same breakout without it.
- N2: The RVOL filter adds nothing versus the r1 filter alone.
- N3: The breakout, with these exits, has no positive expectancy after costs.

**Decision rule:** the strategy is only worth trading if N1, N2, N3 are each rejected in validation *and* the holdout confirms direction (Section 8). Failing N1 or N2 means the paper's hypothesis is not helping in recent data, and we stop and rethink instead of tuning.

---

## 2. Platform constraints and workflow (be honest about TradingView)

- **Indicators cannot place orders or use `strategy.*` statistics.** The indicator therefore *simulates* trades itself (Section 5.6), shows a stats table, exports per-bar data, and fires alerts.
- **TradingView intraday history is limited by plan** and is often much shorter than the 2010-onward split in Section 7. Claude Code must:
  1. Detect the number of available days at runtime and show it in the stats table.
  2. Use **date-based split inputs** (Section 7). If the chart holds too little history for all three splits, the table must display `INSUFFICIENT HISTORY` instead of misleading numbers.
- **Long-history validation and Monte Carlo are done outside Pine.** The indicator exports per-trade data (Section 6.3) to CSV via TradingView's "Export chart data". A separate Python step (Section 9) runs the split analysis and the prop-challenge Monte Carlo. Pine is the signal, display, and alert layer.
- **Volume on continuous futures (`MES1!`, `MNQ1!`) is distorted around contract rolls.** Handle with the exclusion list in Section 3.

---

## 3. Frozen v1 rules (primary configuration)

| Item | Rule (frozen) |
|---|---|
| Session | RTH only, 09:30-16:00 America/New_York |
| Trades per day | Maximum 1 |
| Direction | **Long only** |
| Opening range (OR) | High/low of 09:30-10:00 (30 min) |
| r1 | `close of last bar inside OR / previous RTH close - 1`. On a 1-min chart the last OR bar (09:59) close approximates the 10:00 price |
| Filter A (hypothesis) | Trade only if `r1 > 0` |
| Filter B (volume) | Trade only if `RVOL >= 1.2` |
| RVOL | `OR-window volume today / average OR-window volume of the previous 20 sessions`, strictly backward-looking, excluding today and excluded days |
| Entry signal | First **confirmed** bar after the OR ends whose **close > OR high** |
| Entry fill (simulated) | **Next bar's open** + slippage |
| Entry cutoff | No new entries after 12:30 ET |
| Stop | **OR midpoint**, fixed at entry, never moved |
| Target | **1.5R** where R = entry - stop |
| Backstop exit | Flat at first bar with time >= 15:55 ET, exiting at that bar's open |
| Same-bar stop and target | Assume **stop hit first** (conservative) |
| Gap through stop | Fill at the bar's open if it is below the stop |
| Slippage | 1 tick per side (input, default 1) |
| Commission | $0.62 per side per micro contract (input, default 0.62). Verify against your broker |
| Excluded days | Any date in the `excludeDates` input (roll day and the day after, holidays, half-days). These days are skipped for trading *and* for the RVOL baseline |
| No break-even move, no trailing, no re-entry | Not in v1 |

**Why these defaults:** OR = 30 min mirrors the paper's first half-hour. Stop at midpoint and 1.5R are round, conventional values, not tuned. RVOL 1.2 with a 20-day baseline is a round "above-average participation" definition. The cutoff at 12:30 keeps trades in the part of the day where the hypothesis applies.

---

## 4. Parameter budget (the anti-overfit core)

**Maximum degrees of freedom tested in total: 4 parameters, 3 values each.** Everything else is frozen.

| Parameter | Primary (frozen) | Robustness values (only these) |
|---|---|---|
| OR length | 30 min | 15, 60 |
| RVOL threshold | 1.2 | 1.0, 1.5 |
| Stop | OR midpoint | OR low, entry - 1.0 x ATR(14, daily, prior day) |
| Target | 1.5R | 1.0R, 2.0R |

- Maximum grid = 3 x 3 x 3 x 3 = 81 cells, but **only one-at-a-time changes from the primary are run first** (8 variants). Full-grid runs happen only to draw the plateau heatmap, and are logged as trials.
- **Trial budget: 40 logged variants total** over the whole project (Section 10). Beyond that, the project must restart with new data or a new hypothesis.
- **Baselines that must always be run alongside the primary:**
  - B0: same breakout, **no r1 filter, no RVOL filter**
  - B1: r1 filter only
  - B2: RVOL filter only
  - B3: primary rules but **entry direction randomized** (Python side) to give a luck distribution
- **One extra filter at most, ever.** Candidate: OR width / prior-day ATR (tested as a control for volatility). It may be *tested* against the primary but stacking filters is forbidden until validation shows RVOL adds nothing over it.

---

## 5. Indicator architecture (Pine Script v6)

One indicator: `ORB Long r1+RVOL`, `//@version=6`, `overlay=true`. Chart timeframe must be **1 to 5 minutes**; anything else triggers `runtime.error("Use a 1 to 5 minute chart")`.

### 5.1 Inputs (grouped)
- **Frozen params:** OR length (options 15/30/60), RVOL min, RVOL lookback N, stop mode, target R, entry cutoff (HHMM), flat time (HHMM), slippage ticks, commission per side.
- **Risk / prop:** account size, risk per trade ($), max contracts, profit target, trailing drawdown ($), drawdown type (`EOD` or `Intraday`), daily loss limit, consistency %.
- **Splits (Section 7):** design end date, validation end date, holdout start date, `Unlock holdout` (default false).
- **Data hygiene:** `excludeDates` (comma-separated `YYYY-MM-DD` string), optional volume-source symbol (default = chart symbol; alternative `ES1!` / `NQ1!`).
- **Display:** show levels, show table, show labels.
Every input must have a group and a tooltip. Defaults must equal Section 3.

### 5.2 Session and prior close
```pine
tz    = "America/New_York"
inRTH = not na(time(timeframe.period, "0930-1600", tz))
inOR15 = not na(time(timeframe.period, "0930-0945", tz))
inOR30 = not na(time(timeframe.period, "0930-1000", tz))
inOR60 = not na(time(timeframe.period, "0930-1030", tz))
inOR   = orLen == 15 ? inOR15 : orLen == 30 ? inOR30 : inOR60   // three calls, not a dynamic string
newDay = inRTH and not inRTH[1]

var float prevRthClose = na
var float lastRthClose = na
if newDay
    prevRthClose := lastRthClose
if inRTH
    lastRthClose := close
```
This uses the **RTH** close as "previous close" even when the chart shows extended hours.

### 5.3 Opening range and RVOL (backward-looking only)
```pine
var float orHi = na
var float orLo = na
var float orVol = 0.0
var float r1 = na
var bool  orDone = false
var array<float> orVolHist = array.new<float>()
var float rvol = na

orJustEnded = inRTH and not inOR and inOR[1]

if newDay
    orHi := high
    orLo := low
    orVol := volume
    orDone := false
    rvol := na
    r1 := na
else if inOR
    orHi := math.max(orHi, high)
    orLo := math.min(orLo, low)
    orVol += volume

if orJustEnded
    r1 := close[1] / prevRthClose - 1          // last bar inside OR
    n = array.size(orVolHist)
    if n >= rvolN
        rvol := orVol / array.avg(array.slice(orVolHist, n - rvolN, n))
    if not isExcluded                             // excluded days never enter the baseline
        array.push(orVolHist, orVol)
    orDone := true
```
`orVol` is summed over the OR window only. `rvol` is `na` until N sessions of history exist, and **no trade may occur while `rvol` is na**.

### 5.4 Volatility reference (only for the OR-width control and the ATR stop variant)
```pine
atrPrevDay = request.security(syminfo.tickerid, "D", ta.atr(14)[1], lookahead = barmerge.lookahead_on)
```
The `[1]` plus `lookahead_on` combination is the standard no-repaint pattern for "last completed day". Never use today's daily value.

### 5.5 Signal and simulated trade (state machine)
States: `flat`, `pendingEntry`, `long`. One trade per day via `tradedToday` (reset on `newDay`).
```pine
eligible = orDone and not tradedToday and not isExcluded
        and r1 > 0 and not na(rvol) and rvol >= rvolMin
        and hhmm < entryCutoff
sig = barstate.isconfirmed and eligible and state == 0 and close > orHi
// on sig: state := 1 (pending). On the NEXT bar: fill at open + slip, compute stop/target, state := 2.
```
Management per bar while long (evaluate in this order):
1. Time exit: `hhmm >= flatTime` -> exit at `open`.
2. Stop: if `open <= stop` -> exit at `open` (gap); else if `low <= stop` -> exit at `stop - slippage`.
3. Target: if `high >= target` -> exit at `target` (limit fill, no slippage).
Stop is checked **before** target within the same bar.

Sizing: `contracts = math.floor(riskUSD / (stopDistPts * syminfo.pointvalue))`, capped by max contracts. If `contracts < 1`, **skip the trade** and record it as `SKIPPED (risk too small)`. Use `syminfo.mintick` and `syminfo.pointvalue` for tick and dollar math so the script works on MES and MNQ without edits.

Trade result in R (net of costs):
```
costPts = 2 * slipTicks * syminfo.mintick + 2 * commission / syminfo.pointvalue
netR    = (exitPrice - entryFill - costPts) / (entryFill - stop)
```

### 5.6 Statistics engine
Arrays or `var` accumulators, updated at each closed trade, **per sample**: `design`, `validation`, `holdout` (masked, Section 7), plus `all-visible`.
Per sample report: trades, win rate, average R (expectancy), payoff ratio, profit factor, max losing streak, max drawdown in R, average trade in ticks, skipped trades.
Also report by **RVOL bucket** (fixed, pre-declared edges: `<0.8`, `0.8-1.2`, `1.2-1.6`, `>=1.6`): trades and average R. This is a diagnostic only, never used to change the threshold. (Note: buckets below the filter show what the filter removed, useful for N2.)
Also a **year-by-year** table (trades, total R) to expose dependence on one or two volatile years.
Display in one `table.new(position.top_right, ...)`. Update the table only on `barstate.islast`.

---

## 6. Outputs

### 6.1 Chart
Draw OR box (09:30-end of OR), entry/stop/target lines for the active simulated trade, and a label at exit showing net R. Cap drawing objects (use `max_lines_count`, `max_labels_count`, and delete old ones).

### 6.2 Alerts
- `alert()` at signal confirmation with a JSON-like message: symbol, time, entry reference (signal close), stop, target, contracts, RVOL, r1.
- Separate alerts for: stop hit, target hit, time exit, prop-rule warning (Section 7 buffer below 25%).
- Alerts must fire **once per bar close** (`alert.freq_once_per_bar_close`). The alert is for manual or webhook execution and cannot itself verify the simulated fill.

### 6.3 Data-window exports (for Python validation)
Plot the following with `display = display.data_window` so "Export chart data" contains them per bar:
`r1`, `rvol`, `orHi`, `orLo`, `sigFlag`, `entryFill`, `stopPx`, `targetPx`, `exitPx`, `netR`, `contracts`, `isExcludedDay`, `sampleId` (0 design, 1 validation, 2 holdout), `eventFlag`.
Values are non-na only on the relevant bar (entry bar, exit bar), so the CSV can be filtered to trades in one line.

---

## 7. Data splits, holdout lock, and prop layer

### 7.1 Splits
- **Design:** first 50% of available time (or 2010-2017 if the data reaches that far). All exploration lives here.
- **Validation:** next 25% (or 2018-2021). Used once per candidate variant, after design.
- **Holdout:** final 25% (or 2022 onward). Touched **once**, at the end, for the single frozen candidate.
- Inputs are dates so the same script works at any history depth.

### 7.2 Holdout lock (discipline built into the tool)
- `Unlock holdout` defaults to `false`. While false, trades with `time >= holdoutStart` are **excluded from every statistic and hidden from the equity table**, and the table shows `HOLDOUT LOCKED`.
- The user must write the frozen candidate's parameters in the trial log **before** flipping the switch.
- After unlocking, the table prints a permanent line: `HOLDOUT VIEWED - no further tuning allowed`.

### 7.3 Prop-challenge path check (Pine side, light)
Simulated on the 1-trade-per-day equity path using the configured firm rules:
- Trailing drawdown, `EOD` or `Intraday` method. The intraday method uses the bar's *unrealized* extreme while the trade is open (approximation at bar granularity, stated in the tooltip).
- Daily loss limit, profit target, consistency rule (max share of profit from the best day).
- **Sequential attempts:** when an attempt passes or breaches, a new attempt starts on the next trading day. Report attempts, passes, breaches, average days to pass, and current drawdown buffer.
This is a *path check*, not a probability. Pass probability comes from the Python Monte Carlo (Section 9).

---

## 8. Validation protocol and acceptance criteria

Run in this order. Stop at the first failure.

1. **Sanity/no-bug checks** (Section 11).
2. **Design sample:** run primary, B0, B1, B2. Required: at least **100 trades** for primary. If fewer, the filters are too tight, so report and stop rather than loosen thresholds to get trades.
3. **N1/N2 test (design):** primary average R must exceed B1 which must exceed B0 in direction. If RVOL (B1 to primary) or r1 (B0 to B1) adds nothing, the corresponding hypothesis is not supported, so do not keep the filter "because the paper says so".
4. **One-at-a-time robustness (design):** the 8 neighbor variants from Section 4. Expectancy must stay positive in **at least 6 of 8**. A result that lives in one cell is treated as noise.
5. **Validation (once per candidate):** conditions to advance:
   - at least 60 trades,
   - net average R > 0 and **at least 50% of the design average R** (shrinkage allowed, sign flip not),
   - still positive with costs stressed to **1.5x** (slippage and commission),
   - beats B0 and B1 in validation as well.
6. **Plateau test:** heatmap of average R over (RVOL threshold x target). The chosen cell must be surrounded by positive cells (**at least 70%** of its 8 neighbors positive). Never pick the maximum cell; pick the center of the broad positive zone.
7. **Year-by-year check:** no single year may contribute more than **40%** of total R, and at least 60% of years with trades must be net positive.
8. **Multiple-testing haircut:** report the number of trials so far. With more than ~20 trials, require the validation t-statistic of the mean R to be at least **2.5**, not 2.0.
9. **Holdout (once):** freeze parameters, write them in the log, unlock. Pass = net average R > 0 and within the range of validation results. **Failure means the strategy is rejected, not re-tuned.** The only allowed reaction is to start a new hypothesis on new data.
10. **Prop suitability (Python):** Monte Carlo (Section 9) must show a challenge pass rate and breach rate acceptable to the user *before* trading, with the longest losing streak at least 1.5x smaller than the drawdown buffer in dollars at the chosen risk per trade.

**Explicit anti-patterns to reject:** changing thresholds after seeing holdout, selecting the best of many runs, widening the sample definition to get more trades, adding a filter because one bad year exists, and reporting results without costs.

---

## 9. Python companion (Claude Code, separate deliverable)

Input: the CSV exported from TradingView, plus optionally longer 1-minute data for the same contract.
1. Load trades, split by `sampleId`, recompute stats independently to **cross-check the Pine numbers** (must match to within rounding, otherwise the Pine logic is wrong).
2. r1 -> last-half-hour regression by year (the paper's test) to see whether the raw effect exists in recent data.
3. Bucketed tables: expectancy by RVOL bucket, by year, by day of week, by event flag.
4. Randomized-direction baseline (B3) and a permutation test for the primary's mean R.
5. **Prop Monte Carlo:** bootstrap trades in blocks (block length 5-10 trades to preserve clustering), apply the firm's rules (target, trailing drawdown type, daily limit, consistency, minimum days), 10,000 paths. Report pass rate, breach rate, median days to pass, worst-case losing streak, 5th percentile equity path.
6. Risk-per-trade sweep (fixed grid: 5%, 10%, 15%, 20% of drawdown buffer). Choose by pass rate versus breach rate, not by mean return.

---

## 10. Trial log (mandatory, keep in the repo)

| # | Date | Sample | Variant (only what changed) | Trades | Avg R | Costs stress 1.5x | Kept? | Notes |
|---|---|---|---|---|---|---|---|---|
Every run of any variant, including baselines and discarded ones, is a row. The log is the record used for the multiple-testing haircut. The final report must state: total trials, the primary config, and the holdout result.

---

## 11. Definition of done and test checklist for Claude Code

**Correctness tests (do these before any performance conclusions):**
- [ ] Prior close is the **RTH** close, verified on a day with visible extended-hours movement.
- [ ] `r1` on three hand-checked days matches a manual calculation.
- [ ] `orHi/orLo` reset every day and match manually read values on a 1-minute and a 5-minute chart.
- [ ] RVOL uses only *past* sessions: shifting the data forward by one day must not change today's RVOL.
- [ ] Entry fill = next bar open + slippage (verify on 3 trades).
- [ ] Same-bar stop/target resolves to stop.
- [ ] Gap-through-stop days fill at the open.
- [ ] Time exit at 15:55 works on half-days (or those days are in `excludeDates`).
- [ ] No repainting: reload the chart and compare all signals bar by bar.
- [ ] MES and MNQ both run with no code edits (uses `syminfo.pointvalue`/`mintick`).
- [ ] The holdout mask hides all holdout trades when locked.
- [ ] Skipped trades (`contracts < 1`) are counted, never silently dropped.
- [ ] Object counts stay under TradingView limits on long histories.

**Deliverables:**
1. `orb_long_r1_rvol.pine` (the indicator, v6, commented, inputs grouped).
2. `analysis/` Python package per Section 9.
3. `README.md`: how to load the script, export the CSV, run the analysis, and the unlock procedure.
4. `trial_log.md` initialized with the baseline rows.

**Report back after coding:** list any spec ambiguities you resolved, the assumptions made, and any Pine v6 limitation you hit, without changing the rules yourself.
