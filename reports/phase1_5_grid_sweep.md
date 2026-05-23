# Phase 1.5 Unlock Grid Sweep

_Generated 2026-05-23 20:40 UTC_

## Config

| key | value |
| --- | --- |
| init_cash | 10000.00 |
| fees | 0.000500 |
| slippage | 0.000200 |
| date_start | events.min/events.max |
| date_end | events.min/events.max |

## Top-5 by Sharpe

Top-5 by Sharpe (eligible: n_trades >= 30)

| rank | signal | min_pct | cohort | sharpe | n_trades | win_rate | max_dd | total_return |
| ---: | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | v1 | 0.02 | team | 1.60 | 47 | 76.60% | -2.70% | 18.31% |
| 2 | v1 | 0.02 | team+investor | 1.52 | 63 | 74.60% | -2.79% | 18.69% |
| 3 | v1 | 0.01 | team+investor | 1.50 | 70 | 72.86% | -2.58% | 17.37% |
| 4 | v1 | 0.01 | team | 1.49 | 53 | 73.58% | -2.61% | 16.74% |
| 5 | v1 | 0.02 | all | 1.49 | 79 | 72.15% | -2.67% | 22.09% |

## Eligible Summary

30 of 63 rows are eligible (n_trades >= 30).

## Per-Cohort Breakdown

| cohort | rows | eligible | best_sharpe | total_trades |
| --- | ---: | ---: | ---: | ---: |
| all | 20 | 10 | 1.49 | 1069 |
| team | 20 | 10 | 1.60 | 543 |
| team+investor | 20 | 10 | 1.52 | 718 |
| vesting:cliff | 1 | 0 | n/a | 21 |
| vesting:linear | 1 | 0 | n/a | 0 |
| vesting:step | 1 | 0 | n/a | 29 |
