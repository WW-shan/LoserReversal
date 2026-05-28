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
| v1 | 29 | 1.731 | 0.724 | 7 | 1.01 | 0.714 | -0.721 |
| v2 | 38 | 0.977 | 0.474 | 7 | 0.761 | 0.571 | -0.216 |
| v3 | 40 | 0.495 | 0.575 | 7 | -0.178 | 0.571 | -0.673 |
| v4 | 29 | 0.735 | 0.586 | 6 | -0.199 | 0.333 | -0.934 |
| v5 | 33 | -0.466 | 0.364 | 25 | -0.246 | 0.36 | +0.220 |

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
