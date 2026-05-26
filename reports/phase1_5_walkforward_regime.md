# Phase 1.5 Unlock Walk-Forward

_Generated 2026-05-26 00:29 UTC_

## Methodology

- Walk-forward uses 5 expanding splits with 270 train days and 60 OOS test days.
- Each signal is tuned independently inside the train fold by rerunning min_unlock_pct/cohort cells and requiring n_trades >= 5.
- The lower train threshold is a statistical compromise for sparse single-cohort/min_pct cells; low-trade cells remain high variance.
- If no train cell reaches 5 trades, selection falls back only to the best positive-trade train cell. Splits with no train trades are marked no_train_signal.
- OOS rows apply the train-selected config to test-window events only.
- The portfolio selects top-2 signals by aggregate OOS Sharpe and combines component stats with equal weights.
- Aggregate rows sum n_trades, use total wins over total trades for win_rate, use worst split max_dd, compound total_return, and keep mean per-split Sharpe.
- test_days fallback_used: yes.
- fix_cohort: none.
- stop_loss: none.
- regime_filter: btc-200ma.

## Per-Signal Walk-Forward

| signal | mean OOS Sharpe | total n_trades | aggregate win_rate | worst max_dd | IS-vs-OOS decay |
| --- | ---: | ---: | ---: | ---: | ---: |
| v2 | -0.01 | 1 | 0.00% | -17.50% | 100.89% |
| v5 | -0.05 | 1 | 0.00% | -24.79% | 120.36% |
| v1 | -0.11 | 1 | 0.00% | -14.94% | 107.01% |
| v3 | -0.13 | 1 | 0.00% | -13.78% | 114.09% |
| v4 | -0.20 | 1 | 0.00% | -16.44% | 123.38% |

## Portfolio Walk-Forward

| portfolio | combined Sharpe | n_trades | win_rate | max_dd | total_return |
| --- | ---: | ---: | ---: | ---: | ---: |
| top_2_equal_weight | -0.03 | 2 | 0.00% | -21.14% | -7.31% |

## Verdict-Ready Summary

Best signal by OOS Sharpe: v2, sharpe=-0.01, n_trades=1
No-train-signal splits: 0
If n_trades ≥ 50 AND sharpe ≥ 1.0 → GREEN
If n_trades ≥ 30 AND sharpe ∈ [0.3, 1.0) → YELLOW
Else → RED
Actual classification: RED

## Best-Signal Snapshot

Best signal: v2 with OOS Sharpe -0.01 and 1 OOS trades.
