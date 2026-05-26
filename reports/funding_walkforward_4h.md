# Phase 3 Funding Extreme Contrarian Walk-Forward

_Generated 2026-05-26 02:09 UTC_

## Verdict: RED

OOS Sharpe < 0.5 or negative annualized. The IS edge does not survive out-of-sample selection. Kill funding-extreme as a standalone signal.

## Methodology

- Expanding-window walk-forward at `4h` candle interval: 5 splits, train 270d, test 90d.
- IS step: sweep the same 48-cell grid as `sweep_funding_extreme_grid.py` over the train window; pick top-1 by aggregate Sharpe with n_trades >= 5.
- OOS step: apply the selected (z, hold, lookback) to the test window only; record aggregate Sharpe / annualized / MaxDD / win_rate / n_trades.
- Aggregate row averages OOS Sharpe and annualized over splits, takes worst MaxDD, and pools win_rate by trade count.
- Funding/price slicing uses `(index >= window_start) & (index < window_end)` so splits do not overlap a single 4h bar.

## Config

| key | value |
| --- | --- |
| history_start | 2024-01-20T15:00:00.040000+00:00 |
| history_end | 2026-05-23T00:00:00+00:00 |
| price_interval | 4h |
| n_splits | 5 |
| train_days | 270 |
| test_days | 90 |
| taker_fee | 0.000500 |
| slippage | 0.000200 |

## Per-Split Results

| split | is_start | is_end | oos_start | oos_end | z | hold | lookback | is_n | is_sharpe | oos_n | oos_sharpe | oos_ann | oos_max_dd | oos_win_rate | decay |
| ---: | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 2024-01-20 | 2024-10-16 | 2024-10-16 | 2025-01-14 | 2.0 | 8 | 14 | 1360 | 0.97 | 550 | -3.80 | -40.78% | -14.17% | 45.45% | 4.92 |
| 1 | 2024-01-20 | 2025-01-14 | 2025-01-14 | 2025-04-14 | 3.0 | 168 | 90 | 499 | 0.26 | 0 | n/a | n/a | 0.00% | 0.00% | n/a |
| 2 | 2024-01-20 | 2025-04-14 | 2025-04-14 | 2025-07-13 | 3.0 | 168 | 90 | 586 | 0.27 | 0 | n/a | n/a | 0.00% | 0.00% | n/a |
| 3 | 2024-01-20 | 2025-07-13 | 2025-07-13 | 2025-10-11 | 3.0 | 168 | 90 | 724 | 0.46 | 0 | n/a | n/a | 0.00% | 0.00% | n/a |
| 4 | 2024-01-20 | 2025-10-11 | 2025-10-11 | 2026-01-09 | 2.5 | 168 | 90 | 1260 | 0.56 | 0 | n/a | n/a | 0.00% | 0.00% | n/a |

## Aggregate

| Metric | Value |
| --- | --- |
| OOS Sharpe (mean) | -3.80 |
| OOS annualized (mean) | -40.78% |
| OOS MaxDD (worst) | -14.17% |
| OOS n_trades (sum) | 550 |
| OOS win_rate (pooled) | 45.45% |
| IS Sharpe (mean) | 0.97 |
| IS->OOS decay | 4.92 |

## Verdict thresholds (reframed Phase 3 per blocker.md)

- GREEN: OOS Sharpe >= 1.2 AND annualized >= 20%
- YELLOW: OOS Sharpe in [0.5, 1.2) AND annualized >= 10%
- RED: OOS Sharpe < 0.5 OR negative annualized
