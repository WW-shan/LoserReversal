# Phase 1.5 Bootstrap CI (Bayesian) on v1 OOS

_Generated 2026-05-26 17:46 UTC_

## Methodology

- Input: `data/parquet/phase1_5_walkforward_stop_trades.parquet` filtered to signal=`v1` phase=`OOS` (29 trades).
- Method: `bayesian`.
- Bayesian bootstrap (Rubin 1981) draws Dirichlet(1,...,1) weights on the n=29 trade returns and computes weighted Sharpe per draw.
- Recommended over percentile bootstrap when n<30 (Efron-Tibshirani threshold); weights live on the n-simplex, so each draw is a soft re-weighting rather than a discrete index resample.
- Iterations: 10000 (seed=20260524).
- Sharpe per sample: `weighted_mean / weighted_std * sqrt(14.40)`
- Annualization assumes unlock cadence ~14.4 trades / year (36 trades / 2.5 years).

## Config

| key | value |
| --- | --- |
| input | data/parquet/phase1_5_walkforward_stop_trades.parquet |
| signal | v1 |
| phase | OOS |
| method | bayesian |
| iterations | 10000 |
| seed | 20260524 |
| trades_per_year | 14.4000 |
| n_trades | 29 |

## Bootstrap CI

| statistic | value |
| --- | ---: |
| point Sharpe (annualized) | 1.8377 |
| mean of bootstrap Sharpes | 1.8913 |
| 2.5% percentile (lower CI) | 0.5035 |
| 50% percentile (median) | 1.8812 |
| 97.5% percentile (upper CI) | 3.3224 |

## Decision

- Lower 2.5% CI = 0.5035, Upper 97.5% CI = 3.3224
- Decision rule: lower > 0 = robust; upper < 0 = lucky-fold; else inconclusive.
- **Verdict: robust**

## Implications

- v1 signal Sharpe is statistically distinguishable from zero at 95% confidence (bayesian bootstrap).
- Phase 5 portfolio sizing should use the lower CI bound (0.5035) with fractional Kelly.

