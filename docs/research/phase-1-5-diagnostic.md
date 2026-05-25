# Phase 1.5 YELLOW Diagnostic + 救援 Plan

> Source data: `data/parquet/phase1_5_walkforward.parquet`
> Generated: 2026-05-24
> Decision: this analysis informs whether to upgrade YELLOW → GREEN via 4 ablations

## TL;DR

Phase 1.5 v2 (T-30→T0 short) OOS Sharpe = **0.61** is **YELLOW**. Five root causes identified. Four academic-validated ablations (A/B/C/D) can move it toward GREEN; a fifth (E) requires Phase 3 + Phase 2.5 completion.

## Source data — v2 per-split breakdown

```
split | period          | n  | Sharpe | win% | MaxDD  | ret    | IS-selected cohort
  0   | 2023-10→2024-04 | 5  | 0.09   | 60%  | -17.5% | +1.2%  | all (min_pct=1%)
  1   | 2024-04→2024-09 | 4  | 0.93   | 75%  |  -5.7% | +23.8% | team (min_pct=2%)
  2   | 2024-09→2025-03 | 5  | 0.09   | 60%  | -21.0% | +0.8%  | team+investor (2%)
  3   | 2025-03→2025-09 | 13 | 1.70 🟢| 100% |  -5.6% | +54.7% | team (2%)
  4   | 2025-09→2026-03 | 9  | 0.23   | 56%  | -29.3% | +7.7%  | team (2%)
 AGG  |                 | 36 | 0.61   | 75%  | -29.3% | +110%  |
```

## Five root causes (each cited with academic source)

### 1. Split 3 outlier carries the mean

- Split 3: 1.70 Sharpe on 13 trades (36% of total) — single fold dominates
- Other 4 splits average ≈ 0.34 Sharpe (RED band)
- **Academic root cause (Q6 search dr-6.json)**: "single split is prone to **'lucky fold'** bias — one favorable random or arbitrary split can produce overly optimistic results that fail in live trading"
- **Mitigation**: Bootstrap 95% CI on 36 trade returns to find the true Sharpe range

### 2. IS cohort selection drifts across splits

- 5 splits selected 3 different cohorts: `all` (split 0), `team` (1, 3, 4), `team+investor` (2)
- IS searches across {team, team+investor, all} × {1%, 2%, 5%, 10%} = 12 cells per split
- **Academic root cause (Q1 dr-1.json)**: "Overfitting (Curve-Fitting): A model/strategy fits historical noise rather than true signals... Multiple parameters worsen this by increasing the search space"
- **Mitigation**: Fix cohort = `team` (literature-review.md Part A: team unlocks have -25% avg drawdown, strongest signal)

### 3. Bear-period failure (Split 4)

- 2025-09 → 2026-03 OOS: Sharpe 0.23, MaxDD -29% (worst)
- This is the period when crypto entered correction; unlock shorts likely got squeezed by ETF flow + late-cycle rallies
- **Academic root cause (Q2 dr-2.json + Q5 dr-5.json)**:
  - Q5: "Contrarian shorts during euphoria... persistent upward trends can punish premature shorts via squeezes"
  - Q2: "Regime detection extends [200d MA filter] by classifying market states (e.g., bull, bear, sideways/high-vol)"
- **Note (counterintuitive)**: standard trend filter is "long if BTC > 200d MA". For contrarian short, we want **inverse** filter: short only when BTC < 200d MA (bear regime). Going short in bull market = squeezed.
- **Mitigation**: Gate v2 entries on `BTC_spot < BTC_200d_SMA` (or HMM regime classifier)

### 4. MaxDD -29% blows past GREEN threshold (-20%)

- Even if Sharpe hits 1.0, Phase 1 ROADMAP §231 requires MaxDD ≤ 20%
- Current strategy has no stop loss
- **Academic root cause (Q3 dr-3.json)**: "Event-specific buffers — Wider stops (5-10%+) around news to avoid whipsaws from volatility spikes"
- **Mitigation**: Per-trade stop at -10% (or 2×ATR adaptive)

### 5. Top-2 portfolio Sharpe < v2 alone (counterintuitive)

- v2 alone: 0.61
- v1+v2 equal-weight portfolio: 0.54 (lower!)
- **Academic root cause (Q4 dr-4.json)**: "'Sharpe drag' occurs when high-volatility assets... correlate highly and fail to diversify risk"
- v1 (T-7) and v2 (T-30) share the same thesis around same events → highly correlated
- **Mitigation**: True diversification needs **cross-thesis** signals (unlock + funding + wallet), not cross-window of same thesis
- **Defer**: requires Phase 3 + Phase 2.5 to complete

## Four 救援 ablations (A/B/C/D) + one deferred (E)

### A. Bootstrap CI diagnostic (no strategy change)

**Purpose**: tell us whether 0.61 is robust or lucky-fold
**Method**:
1. Extract 36 trade returns from `phase1_5_walkforward.parquet` v2 OOS rows
2. Resample with replacement 10,000 times
3. Compute Sharpe per bootstrap sample
4. Report 2.5% / 50% / 97.5% percentiles

**Decision rule**:
- 2.5% percentile > 0 → signal is **robust** (worth tuning toward GREEN)
- 2.5% percentile < 0 → signal might be **lucky-fold artifact** (consider accept YELLOW or downgrade)

**Cost**: 1 hour, no strategy change
**Status**: complete — see `reports/phase-1-5-bootstrap-ci.md`. Full-sample CI [0.84, 4.09] (robust); leave-split-3-out CI [-0.47, 2.32] (inconclusive). Headline verdict is robust but regime dependence on split 3 is real.

### B. Fix cohort = team (delete IS lookahead)

**Purpose**: tell us how much of 0.61 came from per-fold cohort search
**Method**:
1. Rerun `run_unlock_walkforward_v15.py` with `--fix-cohort team`
2. Each split uses cohort=team, IS only selects min_pct
3. Compare new Sharpe vs current 0.61

**Decision rule**:
- New Sharpe ≥ 0.6 with team-only → confirms team is the real driver
- New Sharpe < 0.4 → cohort search WAS contributing (overfit) and team alone is weaker than thought

**Cost**: 0.5 day (add CLI flag + rerun)
**Status**: not started

### C. BTC < 200d MA filter (bear-only short entries)

**Purpose**: test if avoiding bull-market squeeze recovers Sharpe
**Method**:
1. Compute BTC 200d SMA daily series 2023-now (we have BTC candles)
2. Filter unlock events: only emit signal when `entry_date_BTC_spot < BTC_200d_SMA(entry_date)`
3. Rerun walk-forward
4. Compare Sharpe + MaxDD + trade count

**Decision rule**:
- Filtered Sharpe ≥ 0.8 AND n_trades ≥ 30 → GREEN candidate via regime filter
- Filtered Sharpe < 0.4 OR n_trades < 20 → regime hypothesis wrong, abandon
- Note: Split 4 (-29% MaxDD) should be heavily reduced by this filter (it was a recovery rally period)

**Cost**: 1 day (signal wrapper + walk-forward rerun)
**Status**: not started

### D. Per-trade -10% stop loss

**Purpose**: reduce MaxDD below 20% (GREEN threshold)
**Method**:
1. Wrap vbt backtest with `stop_loss=0.10` parameter
2. Or implement custom stop in `run_backtest`: exit early if PnL per trade ≤ -10% from entry
3. Rerun walk-forward
4. Compare MaxDD + Sharpe + win_rate

**Decision rule**:
- New MaxDD ≤ 20% → GREEN-eligible on drawdown axis
- Sharpe shouldn't drop more than 0.1 (stop cuts long-tail winners + losers symmetrically)

**Cost**: 0.5 day
**Status**: not started

### E. Cross-thesis portfolio (deferred)

**Purpose**: true Sharpe boost via uncorrelated alpha
**Method**:
1. Wait for Phase 3 (funding extreme contrarian) verdict
2. Wait for Phase 2.5 (wallet contrarian) verdict
3. Risk-parity portfolio composer combines surviving signals
4. Expected Sharpe lift = √N for N uncorrelated signals (if each ≥ 0.5 OOS Sharpe)

**Decision rule**:
- 3 uncorrelated signals each 0.6 Sharpe → portfolio Sharpe ≈ 1.0+ (GREEN)
- Correlation matrix must be < 0.3 between strategies

**Cost**: requires Phase 3 + Phase 2.5 to finish (week+)
**Status**: blocked on prerequisites

## Combined plan: how A+B+C+D might stack

Best-case if all ablations work:
- A (diagnostic) → confirms baseline is robust
- B (fix team cohort) → Sharpe stays 0.6, more stable
- C (regime filter) → cuts bear-period losses → Sharpe jumps to ~0.9
- D (stop loss) → MaxDD from -29% to -12% → meets GREEN drawdown threshold
- Combined: Sharpe ~0.9, MaxDD -12%, n_trades maybe 25-30 (filter reduces sample)

**Worst-case**: A shows CI lower < 0 → accept YELLOW as final
**Middle-case**: only some ablations help → settle for stable YELLOW with proper risk management

## Suggested execution

```
Day 1 morning: A (bootstrap CI) — fast, sets confidence baseline
Day 1 afternoon: B (cohort=team) — directly tests #2 root cause
Day 2: C (regime filter) — tests #3 + addresses split 4 failure
Day 2 PM: D (stop loss) — addresses #4 MaxDD breach
Day 3 morning: combined A+B+C+D rerun → final verdict
Day 3 afternoon: write `phase-1-5-ablation-results.md`, decide GREEN/YELLOW
```

If GREEN: lock v2 with new params into `strategies/active/unlock_v2.json` for Phase 5.
If still YELLOW after all ablations: accept as low-weight portfolio component, proceed to Phase 3.
If clear lucky-fold (A fails): downgrade to RED, no Phase 5 inclusion.
