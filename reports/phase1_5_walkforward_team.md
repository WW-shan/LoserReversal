# Phase 1.5 Unlock Walk-Forward

_Generated 2026-05-25 20:24 UTC_

## Methodology

- Walk-forward uses 5 expanding splits with 270 train days and 180 OOS test days.
- Each signal is tuned independently inside the train fold by rerunning min_unlock_pct/cohort cells and requiring n_trades >= 5.
- The lower train threshold is a statistical compromise for sparse single-cohort/min_pct cells; low-trade cells remain high variance.
- If no train cell reaches 5 trades, selection falls back only to the best positive-trade train cell. Splits with no train trades are marked no_train_signal.
- OOS rows apply the train-selected config to test-window events only.
- The portfolio selects top-2 signals by aggregate OOS Sharpe and combines component stats with equal weights.
- Aggregate rows sum n_trades, use total wins over total trades for win_rate, use worst split max_dd, compound total_return, and keep mean per-split Sharpe.
- test_days fallback_used: no.
- fix_cohort: team.

## Per-Signal Walk-Forward

| signal | mean OOS Sharpe | total n_trades | aggregate win_rate | worst max_dd | IS-vs-OOS decay |
| --- | ---: | ---: | ---: | ---: | ---: |
| v1 | 0.59 | 32 | 75.00% | -14.62% | 63.14% |
| v2 | 0.59 | 33 | 75.76% | -29.30% | 52.76% |
| v4 | 0.35 | 43 | 62.79% | -13.39% | 58.75% |
| v3 | 0.31 | 43 | 65.12% | -17.61% | 65.99% |
| v5 | 0.09 | 32 | 46.88% | -14.68% | 62.44% |

## Portfolio Walk-Forward

| portfolio | combined Sharpe | n_trades | win_rate | max_dd | total_return |
| --- | ---: | ---: | ---: | ---: | ---: |
| top_2_equal_weight | 0.59 | 65 | 75.38% | -17.15% | 73.65% |

## Verdict-Ready Summary

Best signal by OOS Sharpe: v1, sharpe=0.59, n_trades=32
No-train-signal splits: 0
If n_trades ≥ 50 AND sharpe ≥ 1.0 → GREEN
If n_trades ≥ 30 AND sharpe ∈ [0.3, 1.0) → YELLOW
Else → RED
Actual classification: YELLOW

## Best-Signal Snapshot

Best signal: v1 with OOS Sharpe 0.59 and 32 OOS trades.
