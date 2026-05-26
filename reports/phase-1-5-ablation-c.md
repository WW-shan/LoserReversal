# Phase 1.5 Ablation C: BTC < 200d MA regime filter — REJECT

_Generated 2026-05-26 UTC_

## TL;DR

Applying a BTC < 200d SMA bear-regime gate to v2 unlock shorts
collapses sample size to ~1 OOS trade per signal across the 5-split
walk-forward. Best signal v2 ends at Sharpe -0.01 / 1 trade / MaxDD
-17.5%. The walk-forward had to fall back from `test_days=180` to
`test_days=60` to fit splits within the bear-filtered event sequence.

**Decision: REJECT bear-only filter as a standalone fix.** The
hypothesis (Q2/Q5 academic prior: short into trend) is correct in
direction but unusable in practice because:

1. BTC was in sustained bull regime for most of 2024-mid-2025 — bear
   windows that the 200d SMA flags are rare and short.
2. Layered with cohort=team and min_unlock_pct=2%, the surviving event
   set is too sparse for any statistically meaningful walk-forward.

The verdict is the inverse of the original concern: instead of
"Split 4 -29% MaxDD was a bull-trap squeeze," what we actually see is
"Split 4 is one of the few legitimately tradeable bear-period clusters
and removing all other splits leaves no sample."

## Methodology

- Input: `data/parquet/unlocks.parquet` (1768 events), with the
  BTC < 200d SMA gate applied at the CLI entry point via
  `apply_btc_regime_filter` (commit `395f44e`).
- BTC 1d candles backfilled to 2023-01-01 (commit landed earlier this
  session); 200d SMA warms from 2023-07-19 onward.
- Walk-forward: 5 expanding splits, train_days=270, test_days=60
  (auto-fallback from 180 — see methodology line in the raw report).
- Other knobs at defaults: cohort search free, no stop loss.

## Per-Signal Result

| signal | mean OOS Sharpe | total n_trades | win_rate | worst MaxDD | IS→OOS decay |
|---|---:|---:|---:|---:|---:|
| v1 (T-7) | -0.11 | 1 | 0.00% | -14.94% | 107.01% |
| v2 (T-30) | -0.01 | 1 | 0.00% | -17.50% | 100.89% |
| v3 (T-2→+3) | -0.13 | 1 | 0.00% | -13.78% | 114.09% |
| v4 (T-72h) | -0.20 | 1 | 0.00% | -16.44% | 123.38% |
| v5 (T+3→+14 long) | -0.05 | 1 | 0.00% | -24.79% | 120.36% |

Portfolio top-2 equal-weight: Sharpe -0.03, 2 trades, total return -7.31%.

## Why This Fails

The decision rule in `docs/research/phase-1-5-diagnostic.md` Ablation C
said:

> Filtered Sharpe ≥ 0.8 AND n_trades ≥ 30 → GREEN candidate via regime filter
> Filtered Sharpe < 0.4 OR n_trades < 20 → regime hypothesis wrong, abandon

Observed: Sharpe -0.01 AND n_trades 1. Both axes fail by a huge margin.

The Phase 1.5 events span 2023-01 → 2026-05. BTC < 200d SMA windows in
that range:
- Late 2023 chop pre-2024 ETF rally: ~2-3 months
- Early 2025 correction: ~1-2 months
- Late 2025 → early 2026: parts of Split 4

That's ~6 months of bear out of ~30 months of history — about 20% of
the timeline. Combined with the existing filters (cohort=team or all,
unlock_pct ≥ 2%, hl_perp=true, coverage_status=ok), we end up with
roughly 1-2 events per OOS window.

## What This Actually Says About Phase 1.5

The bear-filter result is informative, not just a failed ablation:

1. **The Q2/Q5 academic prior on regime-conditioned shorts is correct
   in direction** — the only Split that produced strongly positive OOS
   Sharpe (Split 3, 1.70) IS in a bear-leaning regime. But the prior
   doesn't help us pick more bear events out of thin air; it just
   identifies that Split 3's lift came from a real regime feature.

2. **Phase 1.5 v2's edge is structurally regime-dependent**, which is
   what the leave-split-3-out bootstrap CI of [-0.47, 2.32] from
   Ablation A already told us. The bear filter confirms this from the
   opposite direction: removing non-bear events leaves no statistical
   floor at all.

3. **The recommended deployment variant remains v1+D** (Sharpe 0.59,
   MaxDD -7.8%, 29 trades from Ablation D). v1's tighter T-7 window
   does not need regime gating because its drawdowns are already
   bounded by short hold time.

## Combined verdict update

This closes the four planned ablations:

| Ablation | Status | Decision |
|---|---|---|
| A bootstrap CI | done | robust full-sample [0.84, 4.09], split-3 dependent |
| B fix cohort=team | done | cohort not the carry; safe to lock team |
| **C BTC<200d MA filter** | **done — REJECT** | **regime is too rare; n_trades collapses** |
| D fixed 10% stop | done | mixed: v1 up, v2 down |

**Final Phase 1.5 verdict: 🟡 YELLOW (unchanged). Best deployable variant
v1 + stop=10% + cohort=team.** Bear filter does not contribute. The
"split 3 carry" remains a structural feature of v2 rather than a
correctable bias; the right answer is portfolio composition (Ablation E)
once Phase 3 and Phase 2.5 land.

## References

- `docs/research/phase-1-5-diagnostic.md` (Ablation C spec, root cause #3)
- `docs/research/phase-3-and-1-5-followups-research.md` (Finding 1 — BTC
  1d backfill unblock)
- `reports/phase1_5_walkforward.md` (baseline 0.61)
- `reports/phase1_5_walkforward_regime.md` (this run's raw output)
- `reports/phase-1-5-ablation-d.md` (the mixed-stop result that pivots
  the recommended variant to v1+D)
- `src/signals/regime_filter.py` (regime computation, commit `8d2d80b`)
- `scripts/run_unlock_walkforward_v15.py::apply_btc_regime_filter`
  (CLI wiring, commit `395f44e`)
- `data/parquet/phase1_5_walkforward_regime.parquet`
