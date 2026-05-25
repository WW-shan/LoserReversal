# Phase 1.5 Ablation A: Bootstrap CI on v2 OOS Sharpe

_Generated 2026-05-25 19:44 UTC_

## Methodology

- Input: `data/parquet/phase1_5_walkforward_trades.parquet` filtered to signal=`v2` phase=`OOS` (36 trades).
- Resampled trade returns with replacement 10000 times (seed=20260524).
- Sharpe per sample: `mean / std(ddof=0) * sqrt(14.40)`.
- Annualization assumes unlock cadence ~14.4 trades / year (36 trades / 2.5 years).
- Note: trade-level Sharpe (~2.18 point estimate) differs from the walk-forward
  Sharpe (0.61) reported in `reports/phase1_5_walkforward.md` because the latter
  is computed on daily mark-to-market equity returns inside vectorbt, which adds
  intra-trade variance the trade-return formulation suppresses. The bootstrap CI
  diagnostic operates on per-trade returns, so the relevant null hypothesis is
  "trade-level Sharpe = 0", not "walk-forward Sharpe = 0".

## Config

| key | value |
| --- | --- |
| input | data/parquet/phase1_5_walkforward_trades.parquet |
| signal | v2 |
| phase | OOS |
| iterations | 10000 |
| seed | 20260524 |
| trades_per_year | 14.4000 |
| n_trades | 36 |

## Bootstrap CI

| statistic | value |
| --- | ---: |
| point Sharpe (annualized) | 2.1815 |
| mean of bootstrap Sharpes | 2.2801 |
| 2.5% percentile (lower CI) | 0.8375 |
| 50% percentile (median) | 2.2220 |
| 97.5% percentile (upper CI) | 4.0882 |

## Decision

- Lower 2.5% CI = 0.8375, Upper 97.5% CI = 4.0882
- Decision rule: lower > 0 = robust; upper < 0 = lucky-fold; else inconclusive.
- **Verdict: robust**

## Per-Split Decomposition

| split | n_trades | mean return | std (ddof=0) | annualized Sharpe |
| ---: | ---: | ---: | ---: | ---: |
| 0 | 5 | 0.0082 | 0.1023 | 0.31 |
| 1 | 4 | 0.2377 | 0.1702 | 5.30 |
| 2 | 5 | 0.0136 | 0.2899 | 0.18 |
| 3 | 13 | 0.2902 | 0.1617 | 6.81 |
| 4 | 9 | 0.0589 | 0.3222 | 0.69 |
| all | 36 | 0.1490 | 0.2591 | 2.18 |

## Lucky-Fold Sensitivity (leave-split-3-out)

Split 3 carries 13/36 trades (36%) and a per-split annualized Sharpe of 6.81.
The diagnostic spec in `docs/research/phase-1-5-diagnostic.md` flagged this as
the primary lucky-fold candidate. To stress-test the verdict, we re-ran the
bootstrap on the remaining 23 trades (splits 0/1/2/4, trades_per_year scaled
proportionally to 9.2).

| statistic | full sample (n=36) | leave-split-3-out (n=23) |
| --- | ---: | ---: |
| point Sharpe (annualized) | 2.18 | 0.78 |
| 2.5% percentile (lower CI) | 0.84 | -0.47 |
| 50% percentile (median) | 2.22 | 0.80 |
| 97.5% percentile (upper CI) | 4.09 | 2.32 |
| decision | robust | inconclusive |

Headline: the full-sample CI excludes zero, but the leave-split-3-out CI
straddles zero. Split 3 is statistically a meaningful contributor and the
"lucky-fold" risk is real, even if it does not flip the headline verdict.

## Implications

- v2 signal Sharpe is statistically distinguishable from zero at 95% confidence
  on the full 36-trade sample. The lower CI of 0.84 sits comfortably above zero,
  which means resampling i.i.d. trade outcomes does not easily reproduce
  Sharpe = 0.
- Caveat: removing split 3 collapses the lower CI to -0.47. Half the bootstrap
  signal comes from one favorable regime (2025-03 to 2025-09). Ablations B/C/D
  should explicitly stress-test this regime dependence rather than assume
  full-sample robustness transfers.
- Proceeding plan:
  - **Ablation B (fix cohort=team)**: high priority. The current 0.61 walk-forward
    Sharpe includes per-fold cohort selection; fixing cohort=team and re-running
    will tell us how much of the result is genuine vs. IS-tuning leakage. If
    B Sharpe stays >= 0.6 with the same trade-level bootstrap CI passing
    `lower > 0`, the regime story holds.
  - **Ablation C (BTC < 200d MA filter)**: medium priority. Splits 0/2/4 sit in
    the 0.18-0.69 Sharpe range and dragged the mean; the regime hypothesis says
    filtering for bear-only entries should lift their per-split Sharpe toward
    the level of splits 1/3. Track filtered trade count - if it drops below 25,
    bootstrap CI will widen and may flip to inconclusive.
  - **Ablation D (-10% stop)**: medium priority. The MaxDD problem is independent
    of the bootstrap result; D is required for GREEN regardless of A/B/C.
- Carry-forward: when reporting the final Phase 1.5 verdict, cite both the
  full-sample CI [0.84, 4.09] AND the leave-split-3-out CI [-0.47, 2.32] so
  downstream readers see the regime dependence.
