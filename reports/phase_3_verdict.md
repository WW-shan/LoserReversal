# Phase 3 — HL Funding Extreme Contrarian: VERDICT RED (data_gap caveat)

> Generated 2026-05-26
> Sources: `data/parquet/funding_walkforward.parquet`, `reports/funding_walkforward.md`,
> `reports/funding_extreme_grid.md`, three-way review trail.

## TL;DR — RED with data_gap caveat

**Phase 3 result: RED on aggregate OOS Sharpe 0.42 / annualized 5.23%.**

The strategy is *not* killed. Caveat: 1h candle backfill only covers
2026-02-23 → 2026-05-23 (~90 days), while funding history covers 3 years
(2023-05 → 2026-05). The walk-forward could only run on the 90-day
overlap; the academic literature alpha-decay horizon for crypto
microstructure signals is ~1 year, so 90 days is far below the
statistical floor needed to confirm or reject the thesis.

This mirrors the Phase 1 v1 "RED was misread as data_gap" lesson. The
verdict is honest but reflects the available data, not the thesis.

## Trail of evidence

### Slice 1 — Data + signal primitive (done, 2026-05-23)
- `data/parquet/funding/*.parquet` — 30 HL perps, funding history back
  to 2023-05.
- `src/signals/funding_extreme_v1.py` — z-score contrarian (entry when
  |z| ≥ threshold, exit on hold_hours or mean revert to 0.5).
- 9 unit tests + smoke. Slice 1 LGTM.

### Slice 2 — Grid sweep + Fix R1 (done, 2026-05-26)
- 48 cells × 18 tokens (12 of 30 funding tokens skipped because no
  matching 1h candles).
- Three-way review (Claude semantic + Codex reviewer + reviewer subagent)
  caught two Critical math bugs in the initial Slice 2:
  - `_sharpe` annualized hourly pct_change by √8760 on a step-function
    equity curve, inflating ratios by ~14×.
  - `_aggregate_equity` ffilled missing tokens with BASE_CAPITAL,
    diluting aggregate Sharpe through phantom idle capital.
- Fix R1 commits: `1456826`, `6f5ac1b`, `33d2aae`, `c039f1c`.
- Headline after fix: top-1 cell (z=3.0 / hold=8 / lookback=14) shifted
  from misleading (Sharpe 2.08, annualized 5.30%) to self-consistent
  (Sharpe 2.12, annualized 20.01%, MaxDD -2.34%, 125 trades). The IS
  sweep on the 90-day window suggested Phase 3 GREEN was plausible.

### Slice 3 — Walk-forward (done, 2026-05-26)
- `src/signals/funding_walkforward.py` — expanding splits; train IS
  picks top-1 cell by aggregate Sharpe; OOS applies that cell.
- `scripts/run_funding_walkforward.py` — CLI with auto history-span
  intersection of funding × candles.
- 13 unit tests covering grid dimensions, split arithmetic,
  GREEN/YELLOW/RED/INCONCLUSIVE matrix, top-Sharpe selection, fallback.
- Initial run with `train_days=270 / test_days=180` returned all
  splits at n/a — funding spans 3 years but candles only 90 days, so
  early splits had zero overlap.
- Re-run with `train_days=30 / test_days=15 / n_splits=3`:

| split | IS Sharpe | IS n | OOS Sharpe | OOS ann | OOS n |
|---|---:|---:|---:|---:|---:|
| 0 | -1.17 | 37 | **6.58** | **36.27%** | 22 |
| 1 | 0.47 | 90 | -4.69 | -18.42% | 6 |
| 2 | 0.52 | 118 | -0.62 | -2.18% | 17 |

Aggregate OOS Sharpe 0.42 / annualized 5.23% / MaxDD -1.37% / 45 trades.

Per-split variance is extreme (6.58 ↔ -4.69 over ~15-day OOS windows
with 6-22 trades each). This is structurally the same "lucky-fold"
pattern Phase 1.5 split 3 exhibited and that the bootstrap CI on
v2 OOS confirmed (CI lower drops below zero when split 3 is removed).

## Verdict

**RED** by the reframed Phase 3 thresholds in
`.ccg/tasks/phase-3-funding-arbitrage/blocker.md`:

- GREEN: OOS Sharpe ≥ 1.2 AND annualized ≥ 20% → 0.42, 5.23% — miss.
- YELLOW: Sharpe ∈ [0.5, 1.2) AND annualized ≥ 10% → 0.42 below floor.
- RED: Sharpe < 0.5 OR negative annualized — triggered.

Not INCONCLUSIVE: n_trades 45 ≥ 30, so the statistical floor is met
on aggregate. But individual splits oscillate so widely that a
bootstrap CI on these 45 trade returns would almost certainly span
zero (mirroring Phase 1.5 ablation A's leave-split-3-out result).

## Caveats (read before acting on this verdict)

1. **90-day data window vs ~1-year alpha-decay horizon.** Crypto
   microstructure literature (see `docs/research/literature-review.md`
   Part B.5) cites 50% signal half-life around 1 year. Validating a
   contrarian funding edge on 90 days is below the statistical floor
   for confident GREEN/YELLOW/RED differentiation — the same problem
   Phase 1 v1 had with 60-day candle backfill being misread as RED.

2. **Split-3 carry pattern.** Split 0 OOS Sharpe 6.58 over 22 trades
   on a 15-day window is well into "lucky cluster" territory. Without
   it the remaining aggregate (Sharpe = mean of -4.69 + -0.62 = -2.66,
   annualized ≈ -10%) is solidly RED but on n_trades 23 only —
   INCONCLUSIVE-eligible.

3. **Token coverage 18 of 30.** 12 funding-history tokens have no
   matching 1h candles: ADA, BNB, DOGE, INJ, LINK, ONDO, PENDLE,
   PENGU, PUMP, WLD, XPL, kPEPE. Tokens missing here include the
   high-trade-count majors (BTC has only 35 hours of 1h data
   actually!), so AGGREGATE is dominated by HYPE / SOL / FARTCOIN /
   ZEC / XMR / AVAX / XRP.

4. **Fee/slippage assumption conservative for IS, possibly optimistic
   for OOS.** `taker_fee=0.0005, slippage=0.0002` reflects calm-market
   HL spreads. Under funding-extreme stress (the exact condition the
   signal targets) realised slippage is often 2-5× higher.

5. **No regime gate.** Phase 1.5 diagnostic identified BTC<200d MA
   bear-only filter as the right move for short-leg contrarian
   strategies. Funding extreme contrarian has the same exposure pattern
   on the positive-z side (crowded longs → contrarian short). A
   regime filter would likely cut OOS variance dramatically.

## Next actions

| Priority | Action |
|---|---|
| 1 | **Extend 1h candle backfill to 2023-05** to match funding history. Run `scripts/backfill_candles.py` with the larger window. Without this Phase 3 cannot be re-validated. |
| 2 | Re-run the full 5-split walk-forward (train_days=270 / test_days=180) once candles cover 3 years. If aggregate OOS Sharpe stays below 0.5 on the extended dataset → final RED. Above 0.5 → upgrade YELLOW. |
| 3 | Defer Phase 3 inclusion in Phase 5 portfolio composition until #1 + #2 land. Phase 5 still has Phase 1.5 v2 YELLOW as the only deployable signal. |
| 4 | Consider funding-extreme + BTC-regime gate (mirror Phase 1.5 Ablation C). Pre-emptive: if the bear-only short-side filter holds OOS, it should be applied here too. |

## Artifacts

- `data/parquet/funding_extreme_grid.parquet` — 48 cells × 18 tokens
- `data/parquet/funding_walkforward.parquet` — 3 splits + aggregate
- `reports/funding_extreme_grid.md` — IS grid report
- `reports/funding_walkforward.md` — walk-forward + verdict
- `reports/phase_3_verdict.md` — this report

## Code modules

- `src/signals/funding_extreme_v1.py` (Slice 1)
- `src/signals/funding_walkforward.py` (Slice 3)
- `scripts/backfill_funding.py` (Slice 1)
- `scripts/run_funding_extreme_backtest.py` (Slice 2)
- `scripts/sweep_funding_extreme_grid.py` (Slice 2)
- `scripts/run_funding_walkforward.py` (Slice 3)

## Validation

- Three-way review per slice (Codex external + reviewer subagent +
  Claude semantic per `claude-verify-must-be-semantic-review.md` memory).
- pytest baseline 370 (was 326 pre-Phase 3); ruff clean.
- 20+ commits across 3 slices, all TDD-paired.
