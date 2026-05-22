# Unlock Short V1 — Walk-Forward Validation

_Generated 2026-05-22 16:12 UTC_

## Verdict: RED
Reason: data_gap

## Data Span
- start: 2025-06-01
- end: 2026-05-15
- total span: 348 days
- n_candidate_events (has_hl_perp): 83

## Walk-Forward Config
- n_splits: 3
- mode: expanding
- min_train_days: 150
- test_days: 60

## Per-Split Results

| split | is_start | is_end | oos_start | oos_end | is_best_config | is_sharpe | is_n_trades | oos_sharpe | oos_n_trades | oos_max_dd | eligible_in_is | is_selection_mode |
| ---: | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | :---: | --- |
| 1 | 2025-06-01 | 2025-10-29 | 2025-10-29 | 2025-12-28 | pre=10 min=0.02 | 2.82 | 2 | n/a | 0 | n/a | no | positive_trades_median |
| 2 | 2025-06-01 | 2025-12-28 | 2025-12-28 | 2026-02-26 | pre=10 min=0.03 | 2.82 | 2 | n/a | 0 | n/a | no | positive_trades_median |
| 3 | 2025-06-01 | 2026-02-26 | 2026-02-26 | 2026-04-27 | pre=7 min=0.02 | 2.23 | 3 | n/a | 0 | n/a | no | positive_trades_median |

## Aggregate OOS Stats

| Metric | Value | Threshold | Status |
| --- | --- | --- | --- |
| OOS Sharpe (mean) | n/a | >= 0.7 (GREEN) / >= 0.3 (YELLOW) | NO SAMPLE |
| OOS Sharpe (min/worst) | n/a | >= 0 desired | NO SAMPLE |
| OOS n_trades (total) | 0 | >= 30 (GREEN) / >= 15 (YELLOW) | FAIL |
| OOS Max DD (worst) | n/a | >= -25% (GREEN) / >= -30% (YELLOW) | NO SAMPLE |
| IS→OOS decay | n/a | <= 30% desired | NO SAMPLE |

## Decision

The verdict is RED because data_gap: OOS Sharpe mean n/a, 0 OOS trades, worst MaxDD n/a, and IS→OOS decay n/a. Recommended action: archive the evidence and skip the unlock-short strategy for Phase 2.
