# Wallet Cluster Reverse V1 - Walk-Forward Validation

_Generated 2026-05-23 17:33 UTC_

## Verdict: RED
> [WARN] walk-forward fallback used
Reason: data_gap

## Data Span
- start: 2026-02-22
- end: 2026-05-23
- total span: 89 days
- n_fills: 116618
- n_wallets_with_fills: 16
- n_failed_wallets: 0

## Walk-Forward Config
- n_splits: 3 (effective: 3)
- mode: expanding
- min_train_days: 120 (effective: 30)
- test_days: 30 (effective: 15)
- top_wallet_n: 50
- grid: 48 configs

## Per-Split Results

| split | is_start | is_end | oos_start | oos_end | is_best_config | is_ir | is_n_trades | oos_ir | oos_daily_sharpe | oos_n_trades | oos_max_dd | eligible_in_is | is_selection_mode |
| ---: | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | :---: | --- |
| 1 | 2026-02-22 | 2026-03-24 | 2026-03-24 | 2026-04-08 | N=3 W=15m H=1h | 0.00 | 1 | n/a | n/a | 0 | n/a | no | positive_trades_any |
| 2 | 2026-02-22 | 2026-04-08 | 2026-04-08 | 2026-04-23 | N=3 W=15m H=1h | 0.00 | 1 | n/a | n/a | 0 | n/a | no | positive_trades_any |
| 3 | 2026-02-22 | 2026-04-23 | 2026-04-23 | 2026-05-08 | N=3 W=15m H=1h | 0.00 | 1 | n/a | n/a | 0 | n/a | no | positive_trades_any |

## Aggregate OOS Stats

| Metric | Value | Threshold | Status |
| --- | --- | --- | --- |
| OOS Trade-level IR (mean) | n/a | >= 1.2 (GREEN) / >= 1.0 (YELLOW) | NO SAMPLE |
| OOS Trade-level IR (min/worst) | n/a | >= 0 desired | NO SAMPLE |
| OOS n_trades (total) | 0 | >= 100 | FAIL |
| OOS Max DD (worst) | n/a | >= -25% | NO SAMPLE |
| IS->OOS decay | n/a | <= 30% desired | NO SAMPLE |

## Decision

The verdict is RED because data_gap: OOS trade-level IR mean n/a, 0 OOS trades, worst MaxDD n/a, and IS->OOS decay n/a. Action: kill the wallet-reverse line and skip Phase 4 sybil clustering.
