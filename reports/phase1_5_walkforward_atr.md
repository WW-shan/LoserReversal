# Phase 1.5 Unlock Walk-Forward

_Generated 2026-05-26 03:17 UTC_

## Methodology

- Walk-forward uses 5 expanding splits with 270 train days and 180 OOS test days.
- Each signal is tuned independently inside the train fold by rerunning min_unlock_pct/cohort cells and requiring n_trades >= 5.
- The lower train threshold is a statistical compromise for sparse single-cohort/min_pct cells; low-trade cells remain high variance.
- If no train cell reaches 5 trades, selection falls back only to the best positive-trade train cell. Splits with no train trades are marked no_train_signal.
- OOS rows apply the train-selected config to test-window events only.
- The portfolio selects top-2 signals by aggregate OOS Sharpe and combines component stats with equal weights.
- Aggregate rows sum n_trades, use total wins over total trades for win_rate, use worst split max_dd, compound total_return, and keep mean per-split Sharpe.
- test_days fallback_used: no.
- fix_cohort: none.
- stop_loss: atr (period=14, multiplier=2.00x, floor=8.00%, cap=25.00%).
- regime_filter: none.

## Per-Signal Walk-Forward

| signal | mean OOS Sharpe | total n_trades | aggregate win_rate | worst max_dd | IS-vs-OOS decay |
| --- | ---: | ---: | ---: | ---: | ---: |
| v1 | 0.59 | 39 | 69.23% | -11.02% | 63.23% |
| v2 | 0.48 | 36 | 52.78% | -16.44% | 61.71% |
| v4 | 0.26 | 29 | 58.62% | -8.98% | 68.54% |
| v3 | 0.20 | 40 | 55.00% | -13.71% | 77.60% |
| v5 | -0.46 | 22 | 31.82% | -14.89% | 298.67% |

## Portfolio Walk-Forward

| portfolio | combined Sharpe | n_trades | win_rate | max_dd | total_return |
| --- | ---: | ---: | ---: | ---: | ---: |
| top_2_equal_weight | 0.53 | 75 | 61.33% | -13.73% | 62.61% |

## Verdict-Ready Summary

Best signal by OOS Sharpe: v1, sharpe=0.59, n_trades=39
No-train-signal splits: 0
If n_trades ≥ 50 AND sharpe ≥ 1.0 → GREEN
If n_trades ≥ 30 AND sharpe ∈ [0.3, 1.0) → YELLOW
Else → RED
Actual classification: YELLOW

## Best-Signal Snapshot

Best signal: v1 with OOS Sharpe 0.59 and 39 OOS trades.
