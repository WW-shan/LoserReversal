# Phase 1.5 Ablation C — Funding-Regime Filter (replaces BTC<200d SMA)

_Generated 2026-05-28 UTC_

## Motivation

BTC<200d SMA filter rejected by Ablation C in 2026-05-26: BTC 1d candle
only 91 days, can't compute 200d SMA. Per smart-search 2026-05-27 finding,
funding-rate regime is a perp-native alternative with 3y data on HL.

## Config

| key | value |
| --- | --- |
| trades input | data/parquet/phase1_5_walkforward_stop_trades.parquet |
| funding dir | data/parquet/funding |
| majors | BTC,ETH |
| window_days | 7 |
| regime span | 2023-06-17 00:00:00+00:00 → 2026-05-23 00:00:00+00:00 |
| % days in bear regime | 13.2% |

## Pre vs Post Filter (per signal)

| signal | n_pre | sharpe_pre | win_pre | n_post | sharpe_post | win_post | Δ_sharpe |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| v1 | 29 | 3.97 | 0.724 | 7 | 1.892 | 0.714 | -2.078 |
| v2 | 38 | 1.994 | 0.474 | 7 | 1.79 | 0.571 | -0.204 |
| v3 | 40 | 1.001 | 0.575 | 7 | -0.334 | 0.571 | -1.335 |
| v4 | 29 | 1.6 | 0.586 | 6 | -0.232 | 0.333 | -1.832 |
| v5 | 33 | -1.002 | 0.364 | 25 | -0.355 | 0.36 | +0.647 |

## Interpretation

- **Positive Δ_sharpe**: funding regime filter helps (drops trades that would have lost).
- **Negative Δ_sharpe**: filter drops winning trades → counterproductive.
- **n_post = 0**: filter rejects all trades (regime never matched) → likely warmup issue.

## Reproducibility

```bash
uv run python scripts/run_funding_regime_eval.py \
  --trades data/parquet/phase1_5_walkforward_stop_trades.parquet \
  --funding-dir data/parquet/funding \
  --majors BTC ETH \
  --window-days 7
```
