# Phase 2.5 Slice 5 — Wallet Reverse Signal Walk-Forward Verdict

_Generated 2026-05-28 UTC_

## Verdict: 🔴 **RED** — Thesis disproven on 21-wallet academic pool

The "reverse academic-pool fills" thesis is empirically disconfirmed at every
percentile threshold. Higher score percentile → more negative Sharpe →
strong monotone signal that the thesis runs in the wrong direction. Flipping
the direction (follow rather than reverse) also fails to produce alpha,
indicating per-fill execution at fill timestamp + 24h hold is not the right
trade construction for these wallets.

## Default run config (percentile=0.75)

| key | value |
| --- | --- |
| scores | data/parquet/reverse_alpha_scores.parquet |
| score_percentile | 0.75 |
| n_splits | 3 |
| mode | expanding |
| min_train_days | 30 |
| test_days | 15 |
| fees | 0.0005 |
| slippage | 0.0002 |
| hold_hours | 24 |
| signal rows | 26460 |
| entries | 13230 |
| coins covered | 33 |
| wallets covered | 21 |

## Percentile sensitivity sweep

Same fill-level walkforward harness (`signals.bot_walkforward`), score
percentile varied from 50th to 95th:

| score percentile | n_paired | Sharpe | win | MaxDD | total_ret | verdict |
|---:|---:|---:|---:|---:|---:|---|
| 0.50 | 193 | +0.374 | 0.202 | -23.9% | +0.3% | RED (sharpe < 0.5) |
| 0.75 | 177 | -0.335 | 0.198 | -22.5% | -8.9% | RED |
| 0.90 | 96 | -0.799 | 0.135 | -23.7% | -10.2% | RED |
| 0.95 | 66 | -1.852 | 0.121 | -23.1% | -18.1% | RED |

**Pattern**: As we tighten the score filter, Sharpe gets steadily *more
negative*. A true alpha signal would show the opposite — tighter filter →
higher Sharpe → fewer but stronger trades. The monotone-negative pattern is
a textbook sign of an **inverted thesis**.

## Per-fold OOS detail (percentile=0.75)

| split | n_trades | Sharpe | win | MaxDD | total_ret |
|---:|---:|---:|---:|---:|---:|
| 0 | 31 | +1.666 | 0.226 | -9.8% | +3.6% |
| 1 | 27 | -3.948 | 0.259 | -7.6% | -6.3% |
| 2 | 13 | +0.370 | 0.077 | -1.5% | +0.2% |

Sign flip across folds — typical noise pattern when underlying signal has no
true edge.

## Direction-flip test at p95

| direction | n_trades | Sharpe | win | MaxDD | total_ret |
|---|---:|---:|---:|---:|---:|
| reverse (original) | 66 | **-1.852** | 0.121 | -23.1% | -18.1% |
| follow (inverted) | 66 | -0.055 | 0.167 | -16.0% | -2.4% |

Follow is **less bad but not profitable** — Sharpe near zero after fees +
slippage. This suggests:

1. **The academic wallets are NOT systematic losers at trade level**: net
   account PnL was negative (selection criterion `realized_loss_rate_90d
   >= 50%`), but individual trade signals don't have alpha.
2. **The 24h hold is likely too long**: academic wallets close positions
   faster than 24h, and we are no longer hedged after they exit.

## Why does this happen? — root cause analysis

The Phase 2.5 Slice 1 academic filter selected wallets by:
- `account_value ∈ [$1k, $100k]` (cohort sized small-to-mid)
- **`realized_loss_rate_90d ≥ 50%`** (net account lost money over 90 days)
- `leverage_avg_90d ≥ 5x`
- `n_trades_90d ≥ 50`
- `size_cv_90d ≥ 0.3`

**Key misread**: "Realized loss rate" measures ACCOUNT-LEVEL net loss, not
TRADE-LEVEL loss. A wallet can:

- Win 80% of its trades (small profits) and lose 20% (large losses) → net
  loser at account level but net WINNER at trade level.
- This matches the empirical 80% trade-level win rate of the wallets — we
  observe 19.8%-20.2% reverse-side win rate at p50, meaning the wallets
  themselves win 79.8%-80.2% of trades.
- Classic "let losers run, cut winners short" retail bias, but the trade
  signal does carry useful information.

This is the same class of finding as **Phase 2 v1's RED reclassification to
FILTER MISDESIGN** (per ROADMAP §259-296). The Phase 2.5 academic filter
correctly identifies *account-level losers*, but those wallets' individual
trades are still better than 50/50 — so reversing them costs us money.

## Implications

### For Phase 2.5 standalone

- **Reverse-fill thesis is dead** on this pool. Cannot deliver YELLOW.
- The 21-wallet academic pool is not big enough to verdict alternative
  thesis variants confidently.

### For Phase 5 gate

- Phase 2.5 Slice 5 does **NOT** add a GREEN/YELLOW signal.
- Phase 5 gate remains 1/2 (Phase 1.5 v1+D YELLOW).

### Possible alternative theses (Phase 2.5 Slice 4+ scope, not yet tested)

1. **Cluster-of-N-academics**: require ≥3 academic wallets agreeing on
   coin × direction within window. Filters out single-wallet noise.
   (This is ROADMAP §494-500 Slice 4 design.)
2. **Hold-duration-aware exits**: exit when the wallet closes its position,
   not after fixed 24h. Requires fill-level position tracking.
3. **Cascade-reversal**: only fire when OI drops X% in 1h (panic event),
   regardless of individual wallet behavior. (Also ROADMAP §494-500.)
4. **Wallet-level aggregation**: trade only when wallet net position swings
   by ≥X%, not on individual fills.

### Walkforward harness deliverables (the actual Slice 5 artifact)

| Artifact | Purpose |
|---|---|
| `src/signals/wallet_reverse_signal.py` | scores → signal frame (percentile + reverse-direction logic) |
| `scripts/run_wallet_reverse_walkforward.py` | CLI: scores → signal → walkforward → report |
| `data/parquet/phase2_5_slice5_walkforward.parquet` | per-fold OOS stats |
| `data/parquet/phase2_5_slice5_trades.parquet` | per-trade returns (for downstream bootstrap CI) |
| `data/parquet/reverse_alpha_scores.parquet` | re-scored on full 21-wallet pool (49,889 rows) |

## Reproducibility

```bash
# Re-fetch 20 missing academic wallet fills (one-off; cached)
# - Used infra.fetchers.user_fills.fetch_user_fills + reset_index() before save

# Re-score all 21 wallets
uv run python scripts/run_reverse_alpha_scoring.py \
  --pool data/parquet/academic_wallet_pool.parquet \
  --fills-dir data/parquet/fills \
  --funding-dir data/parquet/funding \
  --out data/parquet/reverse_alpha_scores.parquet \
  --report reports/reverse_alpha_scoring.md

# Default percentile=0.75 walkforward
uv run python scripts/run_wallet_reverse_walkforward.py

# Sweep percentile to verify monotone-negative pattern
for PCT in 0.50 0.75 0.90 0.95; do
  uv run python scripts/run_wallet_reverse_walkforward.py \
    --score-percentile $PCT \
    --out data/parquet/p2.5_slice5_p${PCT}.parquet \
    --trades-out data/parquet/p2.5_slice5_trades_p${PCT}.parquet \
    --report reports/phase2_5_slice5_p${PCT}.md
done
```

## Pass / Kill thresholds (same as Phase 4 Slice 3)

- GREEN: aggregate OOS Sharpe ≥ 1.5 AND n_trades ≥ 100
- YELLOW: Sharpe ∈ [0.5, 1.5) AND n_trades ≥ 50
- RED: Sharpe < 0.5 OR n_trades < 30
- INCONCLUSIVE: n_trades < 30 (CLT floor)

## Spec evolution candidate

This is a strong candidate for a backend spec rule about how to interpret
filter criteria mismatch:

> "Account-level metrics (realized_loss_rate, net_pnl) do NOT translate to
> trade-level alpha. Per ROADMAP §259-296 (Phase 2 v1 → 2.5 reclassification)
> and Phase 2.5 Slice 5 verdict 2026-05-28, when designing a contrarian
> filter, validate trade-level win rate, not account-level net PnL."
