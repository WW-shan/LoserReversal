# Phase 1.5 — Academic-tuned Unlock Strategy: VERDICT YELLOW

> Generated 2026-05-24
> Verdict source: walk-forward OOS aggregates across 5 splits × 180 OOS days
> Data: 1768 unlock events × 55 HL-perp tokens, 2023-01 → 2026-05

## TL;DR — YELLOW

**Phase 1.5 result: YELLOW** (was Phase 1 RED-mis-read in earlier review)

Best signal — **v2 (T-30 → T0 short, Keyrock long-swing window)**:
- OOS Sharpe **0.61** (in YELLOW band [0.3, 1.0))
- **36 OOS trades** (above 30 threshold)
- 75% win rate
- Total return 110% over 2.5-year OOS test span
- Max drawdown -29%

This is the **first phase to produce a deployable signal**. Will be carried into Phase 5 portfolio composition (low weight, paired with funding arb / wallet contrarian if those also pass).

## Academic alignment

The result strongly validates Keyrock (16k events, 90% negative, T-30 anticipation window). Our finding: 75% win rate on T-30 short converges with the 87.5% pre-event short profit from my own thesis-check (8 events, mean AR -8.21%) and the 88.5% from Kim SSRN 2026 (52 events, T-72h). Across **1768 events** in our pipeline, the *empirical* edge is real but partially decays at OOS — typical of a thesis published in academic literature where the published 90% rate is from controlled retrospective and the live signal is lower.

## Methodology recap

| Param | Value | Rationale |
|---|---|---|
| Events source | DefiLlama emissions-adapters fork (Omni-Chain-Protocols, 310 protocols → 182 parsed → 1768 unlock events) | Phase 1 used 37-protocol fork, only 126 events |
| Candle history | 2023-01-01 → 2026-05-23, 55 HL-perp tokens | Phase 1 had ~90 days, 9/14 events lost entry point |
| Coverage filter | events with `≥60 pre-event days` in audit parquet | Excludes 130/532 HL-perp events that are structurally untradeable |
| Signal grid | 5 academic windows × 4 size thresholds × 3 category cohorts = 60 cells | Phase 1 tested 1 window only |
| Walk-forward | 5 expanding splits × 270 train + 180 OOS days, traverses full 3.4-year span | Phase 1 used 3 splits × 90 days, covered only 27% of data |
| Train selection | per-fold IS Sharpe rank, `min_n_trades=5` (compromise for sparse cohorts) | Phase 1 had no per-fold parameter tuning |

## Funnel

```
DefiLlama emissions-adapters fork              310 protocols
  → parsed                                     182 protocols (drops: 55 no-supply, 48 no-coin-match, 1 no-categories)
  → emitted events                            ~310k raw event-rows (out_of_window=310k, out_of_pct_range=168k)
  → final aggregated events                    1768 unlock events
  → with vesting_type populated                1768 (100%)
  → HL-perp                                    534 events / 55 tokens
  → coverage_status=='ok' (≥60 pre-days)       402 events
  → walk-forward OOS combined                  36 v2 trades (top signal)
```

## Grid sweep highlights (IS, full 3.4-year sample)

Top-5 by Sharpe (eligible, n_trades ≥ 30):

| rank | signal | min_pct | cohort | sharpe | n_trades | win_rate | max_dd | total_return |
|---:|---|---:|---|---:|---:|---:|---:|---:|
| 1 | v1 | 0.02 | team | 1.60 | 47 | 76.6% | -2.7% | 18.3% |
| 2 | v1 | 0.02 | team+investor | 1.52 | 63 | 74.6% | -2.8% | 18.7% |
| 3 | v1 | 0.01 | team+investor | 1.50 | 70 | 72.9% | -2.6% | 17.4% |
| 4 | v1 | 0.01 | team | 1.49 | 53 | 73.6% | -2.6% | 16.7% |
| 5 | v1 | 0.02 | all | 1.49 | 79 | 72.2% | -2.7% | 22.1% |

Vesting sub-sweep (v1 / 2% / team):
- cliff: Sharpe 1.65, 21 trades (best — matches Keyrock's "team cliff = sharper drop")
- step: Sharpe 1.08, 29 trades
- linear: Sharpe 0.0, 0 trades (low qualifying-pct events after split)

## Walk-forward OOS results

Per-signal aggregate (best train-selected config applied to test windows):

| signal | OOS Sharpe (mean) | OOS n_trades (sum) | win_rate (agg) | max_dd (worst) | IS→OOS decay |
|---|---:|---:|---:|---:|---:|
| **v2 T-30→T0** | **0.61** | **36** | **75%** | -29% | 51% |
| v1 T-7→T0 | 0.46 | 28 | 71% | -10% | 71% |
| v4 T-72h→T0 | 0.28 | 29 | 59% | -9% | 67% |
| v3 T-2→T+3 | 0.20 | 42 | 57% | -12% | 78% |
| v5 T+3→T+14 long | 0.06 | 33 | 45% | -14% | 73% |

Portfolio (top-2 = v2 + v1, equal-weighted):
- OOS Sharpe 0.54
- 64 trades
- 73% win rate
- Max DD -17%
- Total return 73%

## Why v1 (IS winner) lost the OOS crown to v2

- v1 T-7 has IS Sharpe 1.60 (small window, high signal precision) but OOS decay is high (71%) — overfit to specific 2024-25 windows
- v2 T-30 captures more of the anticipation pressure and the wider window naturally hedges entry timing — OOS decay only 51%
- Conclusion matches Keyrock: **T-30 is the right window for retail-deployable strategy**; T-7 is sharper-but-fragile

## What this means for the roadmap

✅ **Phase 1.5 YELLOW → continue to Phase 3 (funding arb) + Phase 2.5 (wallet contrarian) + Phase 4 (bot reverse) per priority**
✅ Phase 5 paper trading will run (since at least one phase is GREEN/YELLOW)
🟡 v2 enters Phase 5 portfolio as low-weight candidate, will be re-weighted alongside other surviving signals

## Caveats

1. **n_trades 36 is modest** — formal statistical confidence band on a 0.61 Sharpe with 36 observations is wide. Bootstrap CI would likely span [0.2, 1.0].
2. **OOS span is 2024-04 → 2026-05** — predominantly bullish crypto market. Bear-market behavior unconfirmed.
3. **Active-capital aggregation** — each token gets its own $10k bankroll; for live deployment we need a position-sizing layer (Kelly fractional, max risk per trade, max correlated exposure).
4. **Slippage / funding cost** — `fees=0.05%, slippage=0.02%` per side. Real HL perp slippage during unlock-stress windows can be 2-5× this. Re-run with `fees=0.1%, slippage=0.05%` recommended before live deployment.
5. **Coverage filter excludes 130/532 events** — these are structurally untradeable, not "alpha-bearing-but-skipped". Signal yield could only go down if we shift the filter.

## Artifacts

- `data/parquet/unlocks.parquet` — 1768 events, 100% with vesting_type
- `data/parquet/event_coverage.parquet` — 532 HL-perp events with coverage status
- `data/parquet/unlock_grid_v15.parquet` — 60 main grid cells + 3 vesting sub-sweep
- `data/parquet/phase1_5_walkforward.parquet` — per-split + per-signal + portfolio walk-forward stats
- `reports/phase1_5_grid_sweep.md` — IS grid stats
- `reports/phase1_5_walkforward.md` — OOS walk-forward stats + verdict
- `reports/phase1_5_unlock_academic.md` — this report

## Code modules

- `src/signals/unlock_v1.py` → `unlock_v5.py` — 5 signal variants
- `src/signals/_unlock_common.py` — shared filter + signal emitter
- `src/signals/unlock_grid.py` — registry + grid runner
- `src/signals/unlock_walkforward.py` — walk-forward + portfolio composer
- `src/infra/data_audit.py` — coverage audit helper
- `scripts/backfill_candles.py` — HL candle history backfill
- `scripts/audit_event_coverage.py` — coverage audit CLI
- `scripts/sweep_unlock_grid_v15.py` — grid sweep CLI
- `scripts/run_unlock_walkforward_v15.py` — walk-forward CLI
- `data/seed/parse_emissions.py` — DefiLlama fork parser (extended for vesting_type, fork-supply fallback, community canonicalization)

## Validation

Three-way review per slice (Codex × 2 + Claude semantic). Slice 1/2/3/4 each had a Fix R1 round closing all Critical + Important + Minor findings. Final pytest count: 304 passing, ruff clean.

Total commits: 64 small TDD-paired commits across 5 slices.
