# Phase 4 Slice 3 — Bot Reverse Walk-Forward Verdict

_Generated 2026-05-28 UTC_

## Verdict: 🔴 **RED-INCONCLUSIVE**

The bot cluster reverse signal **fails to produce alpha** on the available wallet
pool. Two failure modes combine to block a clean verdict:

1. **Cluster N ≥ 3 is unreachable** — only 1 paired trade across all (W) at N=3
   threshold-0.3 pool. The Sybil-cluster thesis requires multiple bots agreeing
   on coin × direction × time window; with 13 detected bots whose coin sets
   barely overlap, N≥3 clusters form ~0 events.
2. **N = 2 reaches sample floor only with W ≥ 1440 min (24h)** — and at that
   width the signal **inverts**: aggregate Sharpe -1.88 / MaxDD -23.4% /
   n_trades 28 / win 39%. The "two bots agree → reverse" thesis is
   contradicted by empirical sign.

Narrow-window cells show positive Sharpe (1.5-50x at n_trades < 6), consistent
with the smart-search 2026-05-27 finding that **n < 30 has < 20% statistical
power** and produces wide noise-driven CIs.

## (N, W, threshold) sweep summary

| cell | thr | N_min | W (min) | entries | n_paired | Sharpe | win | MaxDD | verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| thr0.5_n2_w30 | 0.50 | 2 | 30 | 5 | 1 | n/a | 1.00 | 0.0% | INCONCLUSIVE |
| thr0.5_n2_w120 | 0.50 | 2 | 120 | 6 | 2 | 50.7 | 1.00 | 0.0% | INCONCLUSIVE (noise) |
| thr0.5_n2_w240 | 0.50 | 2 | 240 | 11 | 6 | -0.76 | 0.67 | -3.6% | INCONCLUSIVE |
| thr0.5_n2_w480 | 0.50 | 2 | 480 | 18 | 8 | -1.05 | 0.50 | -7.5% | INCONCLUSIVE |
| thr0.4_n2_w30 | 0.40 | 2 | 30 | 7 | 2 | 9.25 | 1.00 | 0.0% | INCONCLUSIVE (noise) |
| thr0.4_n2_w240 | 0.40 | 2 | 240 | 21 | 11 | 0.82 | 0.46 | -4.1% | INCONCLUSIVE |
| thr0.4_n2_w480 | 0.40 | 2 | 480 | 31 | 15 | 0.75 | 0.40 | -8.0% | INCONCLUSIVE |
| thr0.3_n2_w720 | 0.30 | 2 | 720 | 35 | 17 | 1.48 | 0.41 | -8.3% | INCONCLUSIVE |
| **thr0.3_n2_w1440** | **0.30** | **2** | **1440** | **63** | **28** | **-1.88** | **0.39** | **-23.4%** | **INCONCLUSIVE (closest to floor; negative)** |
| thr0.3_n3_w240 | 0.30 | 3 | 240 | 1 | 0 | n/a | n/a | n/a | RED (no signal) |
| thr0.3_n3_w480 | 0.30 | 3 | 480 | 3 | 0 | n/a | n/a | n/a | RED (no signal) |
| thr0.3_n3_w720 | 0.30 | 3 | 720 | 6 | 1 | n/a | 0.0 | 0.0% | INCONCLUSIVE |

## Why this happened

1. **Wallet pool too small**: 50 cached wallets in `data/parquet/fills/` (Phase 2
   v1 anti-alpha cohort) → 13 wallets scoring `bot_score >= 0.3` → 7 wallets
   scoring `>= 0.5`. Sybil thesis literature (Hyperliquid penalized 27k+
   sybil addresses in 2024) operates on **populations 100-1000×** this size.
2. **Coin set divergence**: Most detected "bots" trade only 5-7 coins each
   (2 trade 20+ coins, 1 trades 67). Probability of 3 bots agreeing on
   coin × direction × time within any practical window is ~0.
3. **"Bot" detection picks high-frequency, not dumb-money**: All 7 wallets at
   score=0.5 are 3000-21000-fill traders — likely market makers /
   arbitrageurs, **not retail panic-traders**. Reversing market makers does
   not produce alpha (zero-mean position fluctuations); reversing arb bots
   may actively lose (they're on the right side of price by construction).
4. **Cluster_signal halves entries on pairing**: `cluster_bot_signal` emits
   independent entry / exit rows from `_apply_candidates` state machine.
   Unpaired entries (no matching exit before signal end) drop ~50% of
   entries when backtested.

## Implications

### For Phase 4 Slice 3 standalone

- **Cannot deliver YELLOW/GREEN verdict on current data.**
- Sharpe sign flips with sample size — diagnostic of pure noise.
- Negative-leaning at the largest n (W=1440 → Sharpe -1.88) suggests
  **the inverse thesis is weakly plausible**: follow these "bots", do not
  reverse them. But sample still inconclusive.

### For Phase 5 gate

- Phase 4 Slice 3 does **NOT** add a GREEN/YELLOW signal.
- Phase 5 gate remains 1/2 (only Phase 1.5 v1+D YELLOW).

### Path to a real verdict

1. **Expand wallet pool 10-100×** via HL leaderboard API (build_bot_pool.py
   already supports this; needs 30-60 min API + cache time).
2. **Re-classify "bot" definition**: current detector treats high-trade-count
   wallets uniformly. The Sybil thesis specifically requires *coordinated
   sybil clusters* (shared funding source per
   `wallet_pool.bot_exclusion.funding_source_graph`), not just programmatic
   traders.
3. **Re-run this harness** — code + tests + CLI are now in place, ready for
   data expansion.

### Walkforward harness deliverables (the actual Slice 3 artifact)

| Artifact | Purpose |
|---|---|
| `src/signals/bot_walkforward.py` | Backtest + walkforward + verdict classifier (200+ LOC, 26 tests) |
| `tests/signals/test_bot_walkforward.py` | Full unit coverage of harness (26 tests pass) |
| `scripts/run_bot_signal_walkforward.py` | CLI: signal frame → fold parquet + trades parquet + report |
| `data/parquet/phase4_bot_walkforward_sweep.parquet` | 15-cell (threshold × N × W) sweep summary |
| `data/parquet/bot_wallets.parquet` | 16-wallet bot pool from cached fills |

## Reproducibility

```bash
# 1. Build bot pool from cached fills (one-off helper, see source)
uv run python -c "..." # see commit message for the snippet

# 2. Generate signal frame for one (N, W, threshold) cell
uv run python scripts/run_bot_reverse_signal.py \
  --bot-pool data/parquet/bot_wallets.parquet \
  --fills-dir data/parquet/fills \
  --candles-dir data/parquet/candles \
  --out /tmp/sig.parquet \
  --bot-score-threshold 0.3 --n-bots-min 2 --window-minutes 1440 \
  --hold-hours 24

# 3. Walk-forward verdict
uv run python scripts/run_bot_signal_walkforward.py \
  --signal /tmp/sig.parquet \
  --out data/parquet/phase4_bot_walkforward.parquet \
  --trades-out data/parquet/phase4_bot_walkforward_trades.parquet \
  --report reports/phase4_bot_walkforward.md \
  --n-splits 3 --min-train-days 30 --test-days 15 \
  --fees 0.0005 --slippage 0.0002 --hold-hours 24
```

## Pass / Kill thresholds (per ROADMAP §660 + smart-search 2026-05-27)

- GREEN: aggregate OOS Sharpe ≥ 1.5 AND n_trades ≥ 100
- YELLOW: Sharpe ∈ [0.5, 1.5) AND n_trades ≥ 50
- RED: Sharpe < 0.5 OR n_trades < 30 (after pairing)
- INCONCLUSIVE: n_trades < 30 (CLT floor)
