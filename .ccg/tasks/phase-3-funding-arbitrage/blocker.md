# Phase 3 — Funding Arbitrage / Extreme Contrarian (Revised Plan)

> Original plan: cross-exchange funding arb across Hyperliquid + Binance + Bybit + Bitget
> Revised plan: single-venue HL funding extreme contrarian (geo-block forces this)

## Blocker

From this network/region, the following APIs are **unreachable**:
- `fapi.binance.com` (Binance Futures) — connection timeout
- `api.bybit.com` (Bybit) — connection timeout
- `api.bitget.com` (Bitget) — connection timeout
- `www.okx.com` (OKX) — connection timeout

Working APIs:
- `api.hyperliquid.xyz` — HL `fundingHistory` returns 26k+ samples per symbol back to 2023-05 (excellent)
- `api.gateio.ws` — Gate.io USDT perps available, BUT `funding_rate` endpoint returns only ~1 month history (insufficient for backtest)

Conclusion: **cross-exchange funding arb impossible without VPN / different network**. Single-venue extreme funding contrarian is still viable and is the next-best academic-validated thesis per literature-review.md Part B.5:

> 92% time positive funding bias; extreme >0.05-0.1% per 8h → crowded longs → contrarian short; deep negative <-0.05% → crowded shorts → contrarian long. Direct alpha — separately validated for Phase 2 wallet contrarian timing context.

## Revised Phase 3 thesis

**"HL funding extreme contrarian"**: When 8h funding rate is in the extreme tail (|z-score| > 2 over rolling 30-day window), open contrarian perp position with hold-to-mean-reversion exit.

## Slice breakdown (3 slices, revised)

### Slice 1 — Funding data backfill + signal primitive

- Re-use existing `infra.fetchers.funding.fetch_funding` for HL
- New script `scripts/backfill_funding.py` — pull funding history for all HL-perp tokens that have unlock events OR are in the top 30 by volume, write to `data/parquet/funding/{TOKEN}_8h.parquet`
- New signal module `src/signals/funding_extreme_v1.py`:
  - `funding_extreme_signal(funding_history, prices, z_threshold=2.0, lookback_days=30, hold_hours=24) -> dict[token, (entries, exits)]`
  - Rolling z-score on 8h funding rate
  - Entry: when |z| ≥ threshold, contrarian direction (positive z → short, negative z → long)
  - Exit: after `hold_hours` OR when |z| drops to 0.5 (mean reversion)
- Tests: unit + smoke

### Slice 2 — Backtest + grid sweep

- `scripts/run_funding_extreme_backtest.py`:
  - Per-token backtest using fees + slippage
  - Aggregate stats: n_trades, sharpe, win_rate, max_dd
- Grid:
  - `z_threshold ∈ {1.5, 2.0, 2.5, 3.0}`
  - `hold_hours ∈ {8, 24, 72, 168}` (1×8h, 3×8h, 9×8h, 21×8h)
  - `lookback_days ∈ {14, 30, 90}`
- Total cells: 4 × 4 × 3 = 48

### Slice 3 — Walk-forward + Pass/Kill verdict

- 5-split expanding walk-forward
- Verdict per ROADMAP §312:
  - GREEN: 年化 ≥ 25%, MaxDD ≤ 5%, 触发 ≥ 每周 1-2 次
  - YELLOW: 年化 15-25%
  - RED: 年化 < 15% OR 负收益

## Pass criteria revision

Cross-exchange arb's GREEN threshold was "delta-neutral 25%/yr". Single-venue contrarian thesis is more directional — adjusting:
- GREEN: walk-forward OOS Sharpe ≥ 1.2 AND annualized return ≥ 20%
- YELLOW: walk-forward OOS Sharpe ∈ [0.5, 1.2) AND annualized return ≥ 10%
- RED: walk-forward OOS Sharpe < 0.5 OR negative annualized return

This deviates from ROADMAP §312. Acceptable because Phase 3 was reframed from arb to single-venue contrarian — the original "delta-neutral 25%" criterion doesn't apply to a directional strategy.

---

## Update 2026-05-27: 1h candle backfill 调研结论 (smart-search)

Phase 3 walkforward re-run blocker is **1h candle data extension to 2023-05**
(current coverage: max 2026-02 → 2026-05 ~3 months across 70 tokens).

**Constraints from HL `/info` `candleSnapshot`**:
- Max 5000 candles per single request (hard cap, no pagination)
- IP rate limit: 1200 req/min aggregated, candleSnapshot weighted: 20 base + 1/60 candles → effective ~14.5 batches/min sustainable
- 3-year 1h = 26,280 candles/symbol → ~6 paginated requests/symbol
- For top-20 unlock tokens: ~120 requests × 7s pacing = ~14 min minimum
- For full 70-token backfill: ~50-90 minutes

**Required script changes** (`scripts/backfill_candles.py`):
1. Add time-window pagination loop (current code may only do single-window)
2. Add async-friendly throttle (asyncio.sleep between batches)
3. Add resume/checkpoint pattern (per guides/index.md spec rule — 50min wall qualifies)
4. Add `.partial → os.replace` atomic write per file (per backend/index.md spec)

After backfill: re-run `scripts/run_funding_walkforward.py` with extended data window
2023-05 → 2026-05 using proper 270/180 splits. Re-evaluate per current verdict
thresholds (GREEN ann ≥25%, MaxDD ≤5%, ≥1-2 triggers/week).

Source: smart-search 2026-05-27 — HL gitbook rate-limits + candleSnapshot docs.
