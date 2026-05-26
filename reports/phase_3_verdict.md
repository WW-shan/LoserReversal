# Phase 3 — HL Funding Extreme Contrarian: VERDICT RED

> Generated 2026-05-26
> Sources: `data/parquet/funding_walkforward.parquet`, `reports/funding_walkforward.md`,
> `reports/funding_extreme_grid.md`, `data/parquet/funding_walkforward_4h.parquet`,
> `reports/funding_walkforward_4h.md`, three-way review trail.

## TL;DR — RED confirmed after 4h re-evaluation

**Phase 3 result: RED.** The original 1h-limited walk-forward produced
aggregate OOS Sharpe 0.42 / annualized 5.23% on a 90-day overlap and was
therefore marked RED with a data-gap caveat. The 4h re-evaluation removes
that caveat: 30/30 funding tokens have matching 4h candles, and the full
270d train / 90d test / 5-split walk-forward produced aggregate OOS
Sharpe -3.80 / annualized -40.78% / MaxDD -14.17% / 550 trades.

The funding-extreme contrarian thesis is killed as a standalone Phase 5
candidate unless a new research question adds materially different gates
or portfolio construction.

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

## 4h re-evaluation (2026-05-26)

The 4h rerun resolves the 1h data-gap caveat. Hyperliquid's 5000-candle
cap gives roughly 833 days at 4h resolution, enough for the requested
270d train / 90d test / 5-split design. The rerun artifacts are:

- `data/parquet/funding_extreme_grid_4h.parquet`
- `reports/funding_extreme_grid_4h.md`
- `data/parquet/funding_walkforward_4h.parquet`
- `reports/funding_walkforward_4h.md`

4h grid sweep coverage improved from 18/30 tokens at 1h to 30/30 tokens.
The top aggregate IS grid cell was weak even before walk-forward:
z=3.0 / hold=168h / lookback=30d, Sharpe 0.17, annualized 1.46%,
MaxDD -13.79%, 1945 trades.

4h walk-forward:

| metric | 1h-limited rerun | 4h re-evaluation |
|---|---:|---:|
| candle coverage | 18/30 tokens, ~90 days | 30/30 tokens, ~833 days |
| train/test design | 30d / 15d / 3 splits | 270d / 90d / 5 splits |
| aggregate OOS Sharpe | 0.42 | **-3.80** |
| aggregate OOS annualized | 5.23% | **-40.78%** |
| aggregate OOS MaxDD | -1.37% | -14.17% |
| aggregate OOS trades | 45 | 550 |
| verdict | RED with data_gap caveat | **RED confirmed** |

The 4h run is not a borderline failure. Only split 0 produced OOS trades
under the selected cells, and that split lost sharply: OOS Sharpe -3.80,
annualized -40.78%, win_rate 45.45%. Splits 1-4 selected long-hold cells
that produced no OOS trades in their test windows, which is itself a
deployment failure.

## Verdict

**RED** by the reframed Phase 3 thresholds in
`.ccg/tasks/phase-3-funding-arbitrage/blocker.md`:

- GREEN: OOS Sharpe ≥ 1.2 AND annualized ≥ 20% → -3.80, -40.78% — miss.
- YELLOW: Sharpe ∈ [0.5, 1.2) AND annualized ≥ 10% → miss.
- RED: Sharpe < 0.5 OR negative annualized — triggered on both axes.

Not INCONCLUSIVE: n_trades 550 ≥ 30, and the 4h candle interval covers
all 30 funding tokens over a materially longer window. The prior 1h
data-gap caveat is superseded.

## Caveats (read before acting on this verdict)

1. **The 1h data caveat is superseded, not fixed at 1h.** 1h remains
   HL-API capped to roughly 208 days, but 4h gives enough history for the
   requested design. Future Phase 3 research should default to 4h unless
   it brings an external candle source.

2. **Original lucky-fold carry pattern.** Split 0 OOS Sharpe 6.58 over 22 trades
   on a 15-day window is well into "lucky cluster" territory. Without
   it the remaining aggregate (Sharpe = mean of -4.69 + -0.62 = -2.66,
   annualized ≈ -10%) is solidly RED but on n_trades 23 only —
   INCONCLUSIVE-eligible. The 4h rerun turns this from caveat into
   confirmation: the expanded test loses money instead of preserving the
   lucky-fold uplift.

3. **4h OOS sparsity after selection.** The 5-split 4h walk-forward has
   550 OOS trades in split 0 and zero in splits 1-4. This does not rescue
   the strategy; it means the IS-selected cells are not consistently
   deployable across time.

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
| 1 | Exclude Phase 3 funding-extreme from Phase 5 portfolio composition. |
| 2 | Do not spend more implementation time on the standalone funding-extreme signal without a new research-backed gate. |
| 3 | If revisited, start from 4h candles and test a BTC-regime or volatility gate before any portfolio inclusion discussion. |

## Artifacts

- `data/parquet/funding_extreme_grid.parquet` — 48 cells × 18 tokens
- `data/parquet/funding_walkforward.parquet` — 3 splits + aggregate
- `data/parquet/funding_extreme_grid_4h.parquet` — 48 cells × 30 tokens
- `data/parquet/funding_walkforward_4h.parquet` — 5 splits + aggregate
- `reports/funding_extreme_grid.md` — IS grid report
- `reports/funding_walkforward.md` — walk-forward + verdict
- `reports/funding_extreme_grid_4h.md` — 4h IS grid report
- `reports/funding_walkforward_4h.md` — 4h walk-forward + verdict
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
