# Phase 5 Portfolio Composition

_Generated 2026-05-26 01:25 UTC_

## Config

| key | value |
| --- | --- |
| signals | strategies/active/*.json |
| method | risk_parity |
| target_vol | 0.1500 |
| out | data/parquet/portfolio_composition.parquet |

## Correlation Matrix

| signal | v1+D |
| --- | --- |
| v1+D | 1.0000 |

## Per-Signal Stats

| signal | weight | weight_max | n_trades | win_rate | sharpe | max_dd | sharpe_lower |
| --- | --- | --- | --- | --- | --- | --- | --- |
| v1+D | 0.1000 | 0.1000 | 29 | 0.7241 | 1.8377 | -0.2996 | 0.5035 |

## Kelly Sizing

| signal | ci_lower | ci_median | ci_upper | kelly_fraction | kelly_weight | weight |
| --- | --- | --- | --- | --- | --- | --- |
| v1+D | 0.5035 | 1.8812 | 3.3224 | 0.1004 | 0.1000 | 0.1000 |

## Combined Stats

| metric | value |
| --- | ---: |
| sharpe | 1.8377 |
| max_dd | -29.96% |
| n_trades | 29 |
| win_rate | 72.41% |

## Risk Checks

| check | value | limit | pass |
| --- | --- | --- | --- |
| single_trade_risk <= 1% | 0.0100 | 0.0100 | PASS |
| single_asset_exposure <= 15% | 0.1000 | 0.1500 | PASS |
| total_leverage <= 5x | 0.1000 | 5.0000 | PASS |
| monthly_max_drawdown <= 8% | 0.0777 | 0.0800 | PASS |

## Sources

- `strategies/active/unlock_v1_stop.json` -> `data/parquet/phase1_5_walkforward_stop_trades.parquet`
