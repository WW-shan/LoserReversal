# Funding Extreme Contrarian Grid Sweep

_Generated 2026-05-25 19:52 UTC_

## Methodology

- Each cell runs funding_extreme_signal for every token with matching 1h candles.
- Funding payment is charged as sum(funding_rate x signed position) while held.
- Per-token equity is mark-to-market hourly during open positions; flat between trades.
- Sharpe is annualized off daily-resampled equity returns (periods_per_year=365).
- Aggregate Sharpe uses equal-weight portfolio of per-token daily returns so late-listed tokens do not inflate the denominator with idle BASE_CAPITAL.
- Aggregate equity sums per-token mark-to-market equities; tokens contribute 0 before their first observation.

## Config

| key | value |
| --- | --- |
| funding_dir | /Users/ww/Project/crypto-alpha-portfolio/data/parquet/funding |
| candles_dir | /Users/ww/Project/crypto-alpha-portfolio/data/parquet/candles |
| taker_fee | 0.000500 |
| slippage | 0.000200 |

## Coverage

Aggregate covers **18** of **30** funding tokens.

Skipped (no matching 1h candles or insufficient funding history): ADA, BNB, DOGE, INJ, LINK, ONDO, PENDLE, PENGU, PUMP, WLD, XPL, kPEPE.

## Top-10 by Aggregate Sharpe

Top-10 by Aggregate Sharpe

| rank | z | hold | lookback | n_trades | sharpe | annualized | max_dd | win_rate |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 3.0 | 8 | 14 | 125 | 2.12 | 20.01% | -2.34% | 51.20% |
| 2 | 3.0 | 72 | 14 | 117 | 1.62 | 16.61% | -4.37% | 50.43% |
| 3 | 3.0 | 168 | 14 | 117 | 1.62 | 16.61% | -4.37% | 50.43% |
| 4 | 3.0 | 24 | 30 | 108 | 1.58 | 13.67% | -3.36% | 50.00% |
| 5 | 3.0 | 24 | 14 | 117 | 1.52 | 15.17% | -4.01% | 50.43% |
| 6 | 3.0 | 8 | 30 | 118 | 1.44 | 12.36% | -3.47% | 51.69% |
| 7 | 3.0 | 72 | 30 | 107 | 1.36 | 11.54% | -3.38% | 49.53% |
| 8 | 3.0 | 168 | 30 | 107 | 1.36 | 11.54% | -3.38% | 49.53% |
| 9 | 2.5 | 8 | 14 | 161 | 0.90 | 7.37% | -2.88% | 52.80% |
| 10 | 2.5 | 168 | 14 | 147 | 0.85 | 8.46% | -3.99% | 53.06% |

## Best Per Token

| token | z | hold | lookback | n_trades | sharpe | annualized | max_dd | win_rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| AAVE | 2.0 | 168 | 90 | 6 | 5.43 | 142.15% | -6.44% | 50.00% |
| AVAX | 1.5 | 24 | 30 | 10 | -3.99 | -46.83% | -6.85% | 20.00% |
| BTC | 1.5 | 8 | 14 | 1 | n/a | n/a | -0.80% | 100.00% |
| ETH | 1.5 | 8 | 14 | 0 | n/a | n/a | 0.00% | 0.00% |
| FARTCOIN | 3.0 | 8 | 14 | 15 | 5.58 | 213.19% | -5.23% | 66.67% |
| GMT | 1.5 | 8 | 14 | 0 | n/a | n/a | 0.00% | 0.00% |
| HYPE | 3.0 | 72 | 14 | 46 | 3.05 | 103.13% | -6.65% | 56.52% |
| LIT | 1.5 | 8 | 30 | 4 | n/a | n/a | -1.77% | 75.00% |
| MON | 1.5 | 8 | 90 | 2 | n/a | n/a | -3.97% | 0.00% |
| NEAR | 1.5 | 8 | 14 | 1 | n/a | n/a | -0.43% | 0.00% |
| SOL | 1.5 | 8 | 30 | 51 | 0.08 | -0.99% | -11.67% | 43.14% |
| SUI | 2.5 | 24 | 14 | 5 | 8.35 | 62.17% | -1.48% | 80.00% |
| TAO | 1.5 | 8 | 14 | 0 | n/a | n/a | 0.00% | 0.00% |
| TON | 1.5 | 8 | 14 | 3 | n/a | n/a | -19.46% | 33.33% |
| VVV | 2.5 | 8 | 14 | 6 | -5.73 | -88.84% | -18.95% | 33.33% |
| XMR | 2.5 | 8 | 14 | 18 | 0.66 | 8.56% | -3.50% | 38.89% |
| XRP | 1.5 | 8 | 30 | 11 | -2.89 | -24.89% | -5.23% | 45.45% |
| ZEC | 2.5 | 8 | 90 | 12 | 1.99 | 25.62% | -5.33% | 50.00% |
