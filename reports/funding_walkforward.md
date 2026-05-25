# Phase 3 Funding Extreme Contrarian Walk-Forward

_Generated 2026-05-25 20:06 UTC_

## Verdict: RED

OOS Sharpe < 0.5 or negative annualized. The IS edge does not survive out-of-sample selection. Kill funding-extreme as a standalone signal.

## Methodology

- Expanding-window walk-forward: 5 splits, train 270d, test 180d per Phase 3 plan.
- IS step: sweep the same 48-cell grid as `sweep_funding_extreme_grid.py` over the train window; pick top-1 by aggregate Sharpe with n_trades >= 5.
- OOS step: apply the selected (z, hold, lookback) to the test window only; record aggregate Sharpe / annualized / MaxDD / win_rate / n_trades.
- Aggregate row averages OOS Sharpe and annualized over splits, takes worst MaxDD, and pools win_rate by trade count.
- Funding/price slicing uses `(index >= window_start) & (index < window_end)` so splits do not overlap a single hourly bar.

## Config

| key | value |
| --- | --- |
| history_start | 2026-02-23T01:00:00+00:00 |
| history_end | 2026-05-23T12:00:00+00:00 |
| n_splits | 3 |
| train_days | 30 |
| test_days | 15 |
| taker_fee | 0.000500 |
| slippage | 0.000200 |

## Per-Split Results

| split | is_start | is_end | oos_start | oos_end | z | hold | lookback | is_n | is_sharpe | oos_n | oos_sharpe | oos_ann | oos_max_dd | oos_win_rate | decay |
| ---: | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 2026-02-23 | 2026-03-25 | 2026-03-25 | 2026-04-09 | 3.0 | 8 | 14 | 37 | -1.17 | 22 | 6.58 | 36.27% | -0.12% | 45.45% | -6.62 |
| 1 | 2026-02-23 | 2026-04-09 | 2026-04-09 | 2026-04-24 | 2.5 | 8 | 14 | 90 | 0.47 | 6 | -4.69 | -18.42% | -1.37% | 50.00% | 10.89 |
| 2 | 2026-02-23 | 2026-04-24 | 2026-04-24 | 2026-05-09 | 2.0 | 168 | 14 | 118 | 0.52 | 17 | -0.62 | -2.18% | -0.45% | 58.82% | 2.19 |

## Aggregate

| Metric | Value |
| --- | --- |
| OOS Sharpe (mean) | 0.42 |
| OOS annualized (mean) | 5.23% |
| OOS MaxDD (worst) | -1.37% |
| OOS n_trades (sum) | 45 |
| OOS win_rate (pooled) | 51.11% |
| IS Sharpe (mean) | -0.06 |
| IS->OOS decay | -8.18 |

## Verdict thresholds (reframed Phase 3 per blocker.md)

- GREEN: OOS Sharpe >= 1.2 AND annualized >= 20%
- YELLOW: OOS Sharpe in [0.5, 1.2) AND annualized >= 10%
- RED: OOS Sharpe < 0.5 OR negative annualized
