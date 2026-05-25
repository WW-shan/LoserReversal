# Funding Extreme Contrarian Grid Sweep

_Generated 2026-05-25 06:21 UTC_

## Methodology

- Each cell runs funding_extreme_signal for every token with matching 1h candles.
- Funding payment is charged as sum(funding_rate x signed position) while held.
- Aggregate equity sums per-token equity curves with equal per-token capital.

## Config

| key | value |
| --- | --- |
| funding_dir | data/parquet/funding |
| candles_dir | data/parquet/candles |
| taker_fee | 0.000500 |
| slippage | 0.000200 |

## Top-10 by Aggregate Sharpe

Top-10 by Aggregate Sharpe

| rank | z | hold | lookback | n_trades | sharpe | annualized | max_dd | win_rate |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 3.0 | 8 | 14 | 125 | 2.08 | 5.30% | -0.81% | 51.20% |
| 2 | 3.0 | 24 | 14 | 117 | 1.29 | 3.78% | -1.28% | 50.43% |
| 3 | 3.0 | 72 | 14 | 117 | 1.26 | 3.95% | -1.51% | 50.43% |
| 4 | 3.0 | 168 | 14 | 117 | 1.26 | 3.95% | -1.51% | 50.43% |
| 5 | 3.0 | 24 | 30 | 108 | 0.76 | 1.78% | -1.28% | 50.00% |
| 6 | 2.5 | 8 | 14 | 161 | 0.76 | 1.91% | -1.15% | 52.80% |
| 7 | 2.5 | 168 | 14 | 147 | 0.72 | 2.03% | -1.34% | 53.06% |
| 8 | 3.0 | 72 | 30 | 107 | 0.57 | 1.32% | -1.28% | 49.53% |
| 9 | 3.0 | 168 | 30 | 107 | 0.57 | 1.32% | -1.28% | 49.53% |
| 10 | 3.0 | 8 | 30 | 118 | 0.51 | 1.13% | -1.33% | 51.69% |

## Best Per Token

| token | z | hold | lookback | n_trades | sharpe | annualized | max_dd | win_rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| AAVE | 3.0 | 8 | 14 | 5 | 4.73 | 35.68% | -0.59% | 80.00% |
| AVAX | 2.5 | 24 | 30 | 5 | -4.74 | -38.37% | -4.18% | 20.00% |
| BTC | 1.5 | 8 | 14 | 1 | n/a | n/a | 0.00% | 100.00% |
| ETH | 1.5 | 8 | 14 | 0 | n/a | n/a | 0.00% | 0.00% |
| FARTCOIN | 3.0 | 8 | 14 | 15 | 4.99 | 213.19% | -2.55% | 66.67% |
| GMT | 1.5 | 8 | 14 | 0 | n/a | n/a | 0.00% | 0.00% |
| HYPE | 3.0 | 72 | 14 | 46 | 2.74 | 103.13% | -4.64% | 56.52% |
| LIT | 1.5 | 8 | 30 | 4 | n/a | n/a | -1.24% | 75.00% |
| MON | 1.5 | 8 | 90 | 2 | n/a | n/a | -2.08% | 0.00% |
| NEAR | 1.5 | 8 | 14 | 1 | n/a | n/a | -0.43% | 0.00% |
| SOL | 1.5 | 8 | 30 | 51 | 0.08 | -0.99% | -11.09% | 43.14% |
| SUI | 2.5 | 24 | 14 | 5 | 7.73 | 62.17% | -0.07% | 80.00% |
| TAO | 1.5 | 8 | 14 | 0 | n/a | n/a | 0.00% | 0.00% |
| TON | 1.5 | 8 | 14 | 3 | n/a | n/a | -11.84% | 33.33% |
| VVV | 2.5 | 8 | 14 | 6 | -4.19 | -88.84% | -12.14% | 33.33% |
| XMR | 2.5 | 8 | 14 | 18 | 0.66 | 8.56% | -3.35% | 38.89% |
| XRP | 1.5 | 8 | 30 | 11 | -1.85 | -24.89% | -3.28% | 45.45% |
| ZEC | 2.5 | 8 | 90 | 12 | 1.81 | 25.62% | -3.15% | 50.00% |
