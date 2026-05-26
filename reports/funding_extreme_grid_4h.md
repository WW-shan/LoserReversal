# Funding Extreme Contrarian Grid Sweep

_Generated 2026-05-26 01:20 UTC_

## Methodology

- Each cell runs funding_extreme_signal for every token with matching 4h candles.
- Funding payment is charged as sum(funding_rate x signed position) while held.
- Per-token equity is mark-to-market per 4h bar during open positions; flat between trades.
- Sharpe is annualized off daily-resampled equity returns (periods_per_year=365).
- Aggregate Sharpe uses equal-weight portfolio of per-token daily returns so late-listed tokens do not inflate the denominator with idle BASE_CAPITAL.
- Aggregate equity sums per-token mark-to-market equities; tokens contribute 0 before their first observation.

## Config

| key | value |
| --- | --- |
| funding_dir | /Users/ww/Project/crypto-alpha-portfolio/data/parquet/funding |
| candles_dir | /Users/ww/Project/crypto-alpha-portfolio/data/parquet/candles |
| price_interval | 4h |
| taker_fee | 0.000500 |
| slippage | 0.000200 |

## Coverage

Aggregate covers **30** of **30** funding tokens at the `4h` candle interval.

All funding tokens covered.

## Top-10 by Aggregate Sharpe

Top-10 by Aggregate Sharpe

| rank | z | hold | lookback | n_trades | sharpe | annualized | max_dd | win_rate |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 3.0 | 168 | 30 | 1945 | 0.17 | 1.46% | -13.79% | 49.51% |
| 2 | 3.0 | 168 | 90 | 1294 | 0.11 | 0.57% | -13.17% | 50.31% |
| 3 | 3.0 | 24 | 14 | 2419 | 0.11 | 0.55% | -10.64% | 49.57% |
| 4 | 2.5 | 168 | 90 | 1857 | 0.09 | 0.30% | -15.52% | 50.57% |
| 5 | 3.0 | 168 | 14 | 2319 | 0.07 | 0.19% | -14.04% | 49.72% |
| 6 | 1.5 | 168 | 30 | 5100 | 0.06 | -1.26% | -28.30% | 48.69% |
| 7 | 3.0 | 72 | 30 | 1959 | 0.04 | -0.35% | -14.15% | 49.57% |
| 8 | 2.0 | 8 | 14 | 5311 | 0.04 | -0.35% | -20.30% | 47.56% |
| 9 | 2.5 | 168 | 30 | 2654 | 0.03 | -0.70% | -15.49% | 48.64% |
| 10 | 3.0 | 72 | 14 | 2323 | 0.01 | -0.41% | -14.07% | 49.89% |

## Best Per Token

| token | z | hold | lookback | n_trades | sharpe | annualized | max_dd | win_rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| AAVE | 1.5 | 168 | 14 | 230 | 0.42 | 9.39% | -50.05% | 48.26% |
| ADA | 3.0 | 8 | 14 | 111 | 1.25 | 24.09% | -16.03% | 51.35% |
| AVAX | 3.0 | 72 | 30 | 74 | 1.06 | 30.79% | -16.56% | 48.65% |
| BNB | 3.0 | 72 | 14 | 86 | -0.19 | -3.29% | -20.19% | 45.35% |
| BTC | 1.5 | 168 | 14 | 222 | 1.06 | 23.17% | -15.35% | 52.25% |
| DOGE | 3.0 | 24 | 14 | 98 | 0.73 | 18.11% | -27.96% | 56.12% |
| ETH | 1.5 | 24 | 14 | 272 | -0.05 | -5.30% | -33.54% | 48.16% |
| FARTCOIN | 2.0 | 168 | 90 | 61 | 1.92 | 92.45% | -19.93% | 55.74% |
| GMT | 3.0 | 8 | 90 | 87 | 0.28 | 4.21% | -44.17% | 49.43% |
| HYPE | 3.0 | 72 | 90 | 41 | 0.44 | 5.00% | -21.96% | 46.34% |
| INJ | 2.0 | 168 | 90 | 105 | 1.24 | 54.03% | -36.41% | 55.24% |
| LINK | 3.0 | 8 | 30 | 121 | 0.37 | 6.30% | -26.19% | 47.93% |
| LIT | 1.5 | 8 | 90 | 49 | 1.25 | 53.21% | -11.87% | 53.06% |
| MON | 2.0 | 72 | 30 | 40 | 0.99 | 38.06% | -19.91% | 50.00% |
| NEAR | 3.0 | 24 | 14 | 129 | 1.21 | 35.68% | -20.34% | 51.16% |
| ONDO | 2.0 | 8 | 90 | 170 | 1.86 | 65.54% | -16.66% | 55.88% |
| PENDLE | 1.5 | 168 | 14 | 247 | 0.42 | 9.22% | -51.66% | 45.75% |
| PENGU | 2.0 | 8 | 90 | 82 | 2.23 | 94.87% | -13.95% | 58.54% |
| PUMP | 2.0 | 24 | 14 | 67 | 0.70 | 17.77% | -18.40% | 56.72% |
| SOL | 3.0 | 8 | 90 | 65 | 0.65 | 9.44% | -14.95% | 50.77% |
| SUI | 1.5 | 168 | 90 | 196 | 1.15 | 58.47% | -35.93% | 52.55% |
| TAO | 1.5 | 24 | 90 | 153 | 2.00 | 132.47% | -29.57% | 54.25% |
| TON | 3.0 | 168 | 30 | 69 | 1.07 | 28.06% | -22.28% | 57.97% |
| VVV | 2.0 | 168 | 90 | 47 | 0.29 | 3.24% | -47.48% | 48.94% |
| WLD | 3.0 | 168 | 90 | 64 | 0.04 | -10.41% | -53.02% | 46.88% |
| XMR | 3.0 | 24 | 30 | 22 | 0.56 | 4.29% | -6.81% | 59.09% |
| XPL | 2.5 | 24 | 14 | 45 | 3.20 | 142.63% | -8.02% | 66.67% |
| XRP | 3.0 | 8 | 14 | 117 | 0.26 | 3.11% | -15.66% | 54.70% |
| ZEC | 2.0 | 8 | 14 | 60 | 1.99 | 85.60% | -20.40% | 60.00% |
| kPEPE | 1.5 | 8 | 14 | 350 | 0.58 | 18.61% | -52.36% | 53.14% |
