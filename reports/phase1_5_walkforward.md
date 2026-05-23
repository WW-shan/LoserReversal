# Phase 1.5 Unlock Walk-Forward

_Generated 2026-05-23 22:15 UTC_

## Methodology

- Walk-forward uses 5 expanding splits with 270 train days and 180 OOS test days.
- Each signal is tuned independently inside the train fold by rerunning min_unlock_pct/cohort cells and requiring n_trades >= 5.
- The lower train threshold is a statistical compromise for sparse single-cohort/min_pct cells; low-trade cells remain high variance.
- If no train cell reaches 5 trades, selection falls back only to the best positive-trade train cell. Splits with no train trades are marked no_train_signal.
- OOS rows apply the train-selected config to test-window events only.
- The portfolio selects top-2 signals by aggregate OOS Sharpe and combines component stats with equal weights.
- Aggregate rows sum n_trades, use total wins over total trades for win_rate, use worst split max_dd, compound total_return, and keep mean per-split Sharpe.
- test_days fallback_used: no.

## Per-Signal Walk-Forward

| signal | mean OOS Sharpe | total n_trades | aggregate win_rate | worst max_dd | IS-vs-OOS decay |
| --- | ---: | ---: | ---: | ---: | ---: |
| v2 | 0.61 | 36 | 75.00% | -29.30% | 51.10% |
| v1 | 0.46 | 28 | 71.43% | -9.87% | 71.03% |
| v4 | 0.28 | 29 | 58.62% | -8.98% | 66.97% |
| v3 | 0.20 | 42 | 57.14% | -11.92% | 77.92% |
| v5 | 0.06 | 33 | 45.45% | -14.08% | 72.87% |

## Portfolio Walk-Forward

| portfolio | combined Sharpe | n_trades | win_rate | max_dd | total_return |
| --- | ---: | ---: | ---: | ---: | ---: |
| top_2_equal_weight | 0.54 | 64 | 73.44% | -17.15% | 73.28% |

## Verdict-Ready Summary

Best signal by OOS Sharpe: v2, sharpe=0.61, n_trades=36
No-train-signal splits: 0
If n_trades ≥ 50 AND sharpe ≥ 1.0 → GREEN
If n_trades ≥ 30 AND sharpe ∈ [0.3, 1.0) → YELLOW
Else → RED
Actual classification: YELLOW

## Best-Signal Snapshot

Best signal: v2 with OOS Sharpe 0.61 and 36 OOS trades.
