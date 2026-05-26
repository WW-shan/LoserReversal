# Phase 3 / Phase 1.5 follow-ups — research synthesis

> Generated 2026-05-26 from WebSearch + smart-search-cli (xAI Responses)
> Trigger: "仔细搜索调研一下之前的问题，并思考解决办法"
> Question: how to unblock the data-gap RED (Phase 3) and deferred Ablation C
> (Phase 1.5), and how to fix the v2 + fixed-10% stop loss regression.

## TL;DR — three concrete unblocks

1. **Phase 1.5 Ablation C unblocked immediately.** HL `candleSnapshot` API
   returns 1242 BTC 1d candles (2023-01-01 → 2026-05-26) in a single call;
   the prior 91-row `BTC_1d.parquet` was a backfill-script `--start` setting,
   not an API limit. Cost: 1 backfill rerun. Restores the regime-filter test.

2. **Phase 3 walk-forward unblocked at 4h interval.** Hyperliquid
   `candleSnapshot` has a hard cap of 5000 candles per response. At 4h
   resolution that is 833 days (~2.3 years) — enough for a 5-split
   walk-forward (270 train + 4 × 90 test = 630 days). Academic + practitioner
   sources independently recommend 4h over 1h for funding-extreme contrarian
   strategies: it aligns with the 8h funding cycle, reduces noise, and avoids
   the over-trading drag that inflated Slice 2's IS Sharpe. Switching from
   1h to 4h is a code-level change, no extra data source required.

3. **v2 + fixed-10% stop loss replaceable by ATR-adaptive stop.** vbt
   supports per-bar `sl_stop` arrays via the free `sl_stop = (factor × ATR)
   / close` pattern (no PRO license needed). Standard 2-3× ATR multiplier
   for crypto; pre-event widening for unlock-stress windows.

A fourth finding cautions against over-interpretation of bootstrap CIs at
n=29-36; if v1+D becomes the deployment candidate, prefer Bayesian or
block bootstrap and size from the lower CI bound with fractional Kelly.

## Finding 1 — Hyperliquid candleSnapshot has a 5000-candle hard cap

Authoritative source: Hyperliquid official docs via Chainstack reference.

| interval | 5000 candles ≈ |
|---|---|
| 1m  | 3.5 days   |
| 15m | 52 days    |
| 1h  | 208 days   |
| **4h**  | **833 days (~2.3 years)** |
| **1d**  | **13.7 years**            |

The S3 archive (`s3://hyperliquid-archive`) ships **L2 book snapshots and
asset_ctxs only**, not pre-computed candles. Building 1m/1h candles back
to 2023 would require aggregating from L2 — significant infra work.

### Implication for our local 1h data being only 90 days

The 1h `BTC_1h.parquet` has 35 rows because the backfill was called with
a `--start` 7 days back. Even if rerun today with `--start 2023-01-01`,
the API would still return only the most recent 5000 1h candles (~208
days back from now, so roughly 2025-11 onward). The 1h channel is
genuinely capped — no script change fixes it without external data.

### Three viable workarounds for ≥3-year coverage

| Option | Source | Effort | Recommended |
|---|---|---|---|
| **A. 4h interval via HL API** | Existing `fetch_candles` | low — refactor consumer code | ✅ first pass |
| B. Hydromancer Reservoir | Free S3 with 1-second OHLCV from launch | medium — boto3 + lz4 + resample | secondary if A inadequate |
| C. Aggregate from HL S3 L2 books | HL official archive | high — requester-pays + lz4 + L2 → candle | last resort |
| D. Incremental record over months | Run HL API daily | very high latency | reject |

### Concrete plan (Option A — 4h interval)

1. Backfill: `python scripts/backfill_candles.py --interval 4h
   --start 2023-05-12 --end 2026-05-23` (matches funding span).
2. Refactor `src/signals/funding_extreme_v1.py` to accept 4h price index
   alongside 8h funding ticks. `_funding_tick` already aligns funding to
   any price bar — should require no signal-layer change.
3. Refactor `scripts/run_funding_extreme_backtest.py::load_prices` to
   read `*_4h.parquet` instead of `*_1h.parquet`. Add a CLI flag
   `--price-interval {1h,4h}` for back-compat.
4. Refactor `_sharpe` daily-resample logic — unchanged (4h → daily resample
   still works).
5. Re-run Slice 2 grid sweep + Slice 3 walk-forward on 4h data with
   train_days=270 / test_days=90 / n_splits=5.
6. Compare Phase 3 RED-data_gap verdict vs the 4h re-run; expect the
   genuine signal-or-no-signal answer.

## Finding 2 — BTC 1d back to 2023-01-01 is one command away (実测)

```bash
uv run python -c "
from datetime import datetime, timezone
from infra.fetchers.candles import fetch_candles
df = fetch_candles('BTC', '1d',
    datetime(2023,1,1,tzinfo=timezone.utc),
    datetime(2026,5,26,tzinfo=timezone.utc))
print(len(df))   # 1242
"
```

The current `BTC_1d.parquet` (91 rows) is purely a backfill script
side-effect. Fix:

```bash
uv run python scripts/backfill_candles.py --interval 1d \
  --start 2023-01-01T00:00:00 \
  --end   2026-05-26T00:00:00 \
  --tokens BTC
```

After this lands, Ablation C is unblocked: 1242 daily bars are well
above the 200d SMA warmup. Wire `--regime-filter btc-200ma` into
`scripts/run_unlock_walkforward_v15.py` (regime_filter module is
already committed `8d2d80b`).

## Finding 3 — ATR-adaptive stop loss for v2

The fixed 10% stop killed v2 (Sharpe 0.61 → 0.27, win 75% → 47%)
because T-30 holds traverse multi-week price oscillations where
mean-reverters dip past 10% mid-hold and recover before exit.

vbt free version supports per-bar `sl_stop` as a fraction-of-close
array. Standard ATR-stop formula:

```python
import vectorbt as vbt
atr = vbt.IndicatorFactory.from_talib("ATR").run(
    high, low, close, timeperiod=14
).real
# fraction-of-close per-bar stop with 2× ATR multiplier
sl_pct = (atr * 2.0 / close).fillna(method="bfill")
pf = vbt.Portfolio.from_signals(
    close=close, entries=entries, exits=exits,
    sl_stop=sl_pct, ...,  # array, not scalar
)
```

Crypto-specific best practice (synthesized across LuxAlgo, Flipster,
Mudrex):

- Use 14-21 period ATR; BTC daily ATR runs 3-7% so absolute stops vary 6-15%
- 2× ATR baseline; widen to 3× ATR around event windows
- Pre-event widening: at T-1 around unlock day, widen multiplier 50%
- Chandelier-exit variant trails from lowest-low for shorts (locks profit)

### Caveat the search literature flags

Mean-reversion / contrarian strategies are NOT ATR's strongest use case:
ATR widens during high volatility, which is exactly when contrarian
entries fire. So adaptive stops will be wider than fixed at entry. For
v2 this is actually a **feature, not a bug** — the wide T-30 window
needs wider stops to avoid clipping winners. Adapted version should:

1. Compute ATR per token per day
2. Translate to per-trade sl_pct at entry timestamp
3. Cap at 25% (don't let runaway-vol blow up risk budget)
4. Floor at 8% (don't go below the academic event-buffer minimum)

Expected: v2 Sharpe recovers toward 0.4-0.5 (vs fixed-10% 0.27), MaxDD
stays in the -15 to -22% band (vs fixed-10% -20%).

## Finding 4 — small-sample bootstrap CI caveats at n=29

Phase 1.5 v1+D has 29 OOS trades. Standard percentile bootstrap is
borderline:

- Efron-Tibshirani rule of thumb: n ≥ 30 for reasonable bootstrap behavior
- Wu (1986): n ≥ 50-60 for standard-error stability
- For 95% CIs specifically, ≥ 100 is conservative
- n=29 risks: spurious CIs that exclude the true mean, especially when
  the underlying distribution has fat tails (crypto definitely does)

### Better techniques for n<30

1. **Bayesian bootstrap** — recent (2025) literature shows superior
   coverage at small n. Easy implementation: weight each observation
   with a Dirichlet(1,...,1) draw, then resample.
2. **Block bootstrap (stationary)** — preserves serial autocorrelation
   in trade returns; appropriate when trades cluster around unlock events.
3. **BCa intervals** — bias-corrected and accelerated; standard upgrade
   over percentile bootstrap.

### Sizing implication

When sizing v1+D into Phase 5 portfolio, take the **lower CI bound**
of OOS Sharpe (not the 0.59 point estimate) and apply ¼-Kelly on top.
If lower CI < 0.3, treat the signal as a low-conviction sleeve
(2-5% portfolio weight) rather than a primary allocation.

## Decision matrix — next 5 actions in priority order

| # | Action | Effort | Unblocks |
|---|---|---|---|
| 1 | `backfill_candles --interval 1d --start 2023-01-01 --tokens BTC` | 5 min | Ablation C |
| 2 | Wire `--regime-filter btc-200ma` into `run_unlock_walkforward_v15.py` + run Ablation C | 30 min | Phase 1.5 GREEN/YELLOW decision |
| 3 | Refactor Phase 3 stack to 4h interval (backfill + signal + sweep + walkforward) | 0.5 day | Phase 3 honest verdict |
| 4 | Implement ATR-adaptive stop on v2 (vbt array `sl_stop`) | 0.5 day | v2 deployable with bounded MaxDD |
| 5 | Bayesian bootstrap CI on v1+D 29 trades | 1 hour | Phase 5 weight sizing |

Items 1-2 are quick wins that close Phase 1.5 救援 properly. Item 3
genuinely answers the Phase 3 question (RED vs YELLOW vs GREEN). Items
4-5 are polish that improve portfolio-stage confidence.

## Sources

- Hyperliquid candleSnapshot API limit:
  [Chainstack reference](https://docs.chainstack.com/reference/hyperliquid-info-candle-snapshot),
  [Hyperliquid official historical data docs](https://hyperliquid.gitbook.io/hyperliquid-docs/historical-data),
  [Hyperliquid info endpoint](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint)
- Hydromancer Reservoir 1-second OHLCV:
  [Hydromancer Hyperliquid historical data](https://hydromancer.xyz/hyperliquid-historical-data)
- Community CLI for L2 book extraction:
  [c-i/hyperliquid-historical](https://github.com/c-i/hyperliquid-historical)
- ATR-adaptive stop:
  [LuxAlgo 5 ATR stop strategies](https://www.luxalgo.com/blog/5-atr-stop-loss-strategies-for-risk-control/),
  [Mudrex ATR settings](https://mudrex.com/learn/average-true-range-crypto/),
  [Flipster ATR stop](https://flipster.io/blog/atr-stop-loss-strategy),
  [LuxAlgo volatility-stop indicator](https://www.luxalgo.com/blog/volatility-stop-indicator-volatility-based-trailing-stop-strategy/)
- vbt per-bar sl_stop:
  [vectorbt stop-based exits (DeepWiki)](https://deepwiki.com/polakowo/vectorbt/4.2-stop-based-exit-signals),
  [vbt cookbook backtest part 3](https://medium.com/@Tobi_Lux/backtesting-using-vectorbt-cookbook-part-3-c22646b02928)
- 4h vs 1h interval for funding contrarian:
  [quantjourney funding rates](https://quantjourney.substack.com/p/funding-rates-in-crypto-the-hidden),
  [altrady funding rate strategies](https://www.altrady.com/blog/crypto-trading-strategies/crypto-funding-rates-explained),
  [fulgur ventures bitcoin funding price predictability](https://medium.com/@fulgur.ventures/bitcoin-funding-rates-and-price-predictability-27ce95535af1),
  [MDPI funding rate two-tiered structure](https://www.mdpi.com/2227-7390/14/2/346)
- Small-sample bootstrap:
  [ResearchGate Bayesian bootstrap CI for small n](https://www.researchgate.net/publication/398911444_Bayesian_Bootstrap_Confidence_Interval_for_Mean_based_on_Small_Sample_Sizes),
  [arXiv 2402.09397 bootstrap intervals fixed size](https://arxiv.org/pdf/2402.09397),
  [crypto simulation stationary bootstrap](https://arxiv.org/html/2512.02029v1)
