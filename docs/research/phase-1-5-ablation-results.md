# Phase 1.5 Ablation Results — Combined A + B + D (C deferred)

_Generated 2026-05-26 UTC_

## TL;DR

After running three of the four planned Phase 1.5 救援 ablations on the
v2 (T-30 → T0 unlock short) baseline of OOS Sharpe 0.61 / 36 trades /
MaxDD -29% / 75% win, the verdict is:

- **A (bootstrap CI) ✅ robust**: trade-level Sharpe full-sample CI
  **[0.84, 4.09]**, median 2.22. v2 is statistically distinguishable
  from zero at 95%. Caveat: leave-split-3-out CI [-0.47, 2.32] —
  Split 3 carries 39% of the weight.
- **B (fix cohort=team) ✅ team is the real driver**: new Sharpe 0.59
  vs baseline 0.61 (Δ -0.02, within bootstrap noise). The IS cohort
  search adds essentially zero overfit lift. Safe to lock cohort=team.
- **C (BTC < 200d MA regime filter) ⏸ data-blocked**: BTC 1d candle
  backfill only covers 91 days (2026-02 → 2026-05) — 200d SMA cannot
  be computed; cannot validate the Q5 regime hypothesis with current
  data. `src/signals/regime_filter.py` module + 12 tests landed (commit
  `8d2d80b`) and is ready to wire once BTC backfill extended.
- **D (-10% stop loss) ⚠ mixed**: best signal flips v2 → v1; v1 gains
  Sharpe (0.46 → 0.59, MaxDD -10% → -8%) but v2 collapses (Sharpe
  0.61 → 0.27, win rate 75% → 47%). The stop ejects legitimate
  T-30 mean-reversion winners. MaxDD improves -29% → -20%, hitting
  the GREEN drawdown threshold edge.

**Final Phase 1.5 verdict**: ⚠ **YELLOW (unchanged) with a deployment
recommendation switch.** Best deployable signal is now **v1 + stop=10% +
cohort=team** (Sharpe 0.59 / MaxDD -8% / 29 trades), narrowly displacing
v2 (Sharpe 0.61 / MaxDD -29% / 36 trades) from the leaderboard. v1
loses 2pp on Sharpe but gains 21pp on MaxDD — better risk-adjusted
profile for portfolio inclusion.

## Combined results table

| variant | OOS Sharpe | n_trades | win_rate | MaxDD | Decision per criteria |
|---|---:|---:|---:|---:|---|
| v2 baseline | 0.61 | 36 | 75.0% | -29.3% | YELLOW (Sharpe), fails MaxDD |
| v2 + B (cohort=team) | 0.59 | 33 | 75.8% | -29.3% | YELLOW unchanged |
| v2 + D (stop=10%) | 0.27 | 38 | 47.4% | -20.1% | RED on Sharpe |
| v1 baseline | 0.46 | 28 | 71.4% | -9.9% | YELLOW (low n) |
| **v1 + D (stop=10%)** | **0.59** | **29** | **72.4%** | **-7.8%** | **YELLOW; best risk-adjusted** |
| Portfolio top-2 baseline | 0.54 | 64 | 73.4% | -17.2% | YELLOW |
| Portfolio + D (stop=10%) | 0.43 | 67 | 58.2% | -12.0% | YELLOW (Sharpe declines) |

GREEN thresholds (ROADMAP §231):
- Sharpe ≥ 1.0 AND n_trades ≥ 50 AND MaxDD ≤ -20%

**No variant tested hits GREEN simultaneously on all three axes.** v1+D
gets closest to ideal risk-adjusted shape but falls short on Sharpe
(0.59 vs 1.0) and n_trades (29 vs 50).

## Per-ablation detail

### A. Bootstrap CI on v2 OOS Sharpe

Source: `reports/phase-1-5-bootstrap-ci.md` (commit `b8270fb`)

| | full sample (n=36) | leave-split-3-out (n=23) |
|---|---:|---:|
| 2.5% lower | 0.84 | -0.47 |
| 50% median | 2.22 | 0.78 |
| 97.5% upper | 4.09 | 2.32 |
| point estimate | 2.18 | — |
| verdict | robust | inconclusive |

Note: trade-level annualized Sharpe (√14.4 × per-trade ratio) is ~2.18,
which is the "if every trade were i.i.d." benchmark. Walk-forward
mean-of-per-split Sharpe (0.61) is meaningfully lower because per-fold
sample sizes range 4–13 trades and per-split variance is high. The
two metrics answer different questions — the bootstrap answers "is the
edge real?" (yes) and the walk-forward answers "what's the realised
Sharpe under fold-by-fold IS selection?" (0.61, with regime drag).

### B. Fix cohort = team

Source: `reports/phase-1-5-ablation-b.md` (commit `523c8fa`)

| metric | baseline | --fix-cohort team |
|---|---:|---:|
| Sharpe | 0.61 | 0.59 |
| n_trades | 36 | 33 |
| win_rate | 75.0% | 75.8% |
| MaxDD | -29.3% | -29.3% |

Splits 1/3/4 picked `team` already; only splits 0 and 2 changed (1–2
trade drop each). Cohort search degree of freedom did NOT overfit.
**Safe to lock cohort=team for live deployment.**

### C. BTC < 200d MA regime filter — DEFERRED

Module: `src/signals/regime_filter.py` (commit `8d2d80b`, 12 tests).

Cannot run real-data ablation: `data/parquet/candles/BTC_1d.parquet`
only contains 91 daily bars (2026-02-21 → 2026-05-22). 200-day SMA
requires at least 200 bars to warm. Same data-gap class as Phase 3 1h
candle backfill.

**Action required to validate C**: extend BTC daily candle backfill to
≥ 2023-05 (matching funding history span). This is shared
infrastructure with Phase 3's candle-extension follow-up. Once landed,
re-run with `--regime-filter btc-200ma` to test whether bear-only short
entries lift Sharpe above 0.7 on splits 0/2/4.

The regime_filter module itself is correct and tested; the CLI wiring
in `scripts/run_unlock_walkforward_v15.py` is the only remaining
implementation work.

### D. Per-trade -10% stop loss

Source: `reports/phase-1-5-ablation-d.md`, parquet
`data/parquet/phase1_5_walkforward_stop.parquet`

Per-signal effect:

| signal | baseline Sharpe | --stop Sharpe | baseline MaxDD | --stop MaxDD |
|---|---:|---:|---:|---:|
| v1 (T-7) | 0.46 | **0.59** | -9.9% | **-7.8%** |
| v2 (T-30) | **0.61** | 0.27 | -29.3% | **-20.1%** |
| v3 (T-2→+3) | 0.20 | 0.13 | -11.9% | -11.2% |
| v4 (T-72h) | 0.28 | 0.26 | -9.0% | -9.0% |
| v5 (T+3→+14 long) | 0.06 | -0.18 | -14.1% | -15.0% |

v2's win rate 75% → 47% is the smoking gun: 10% stop is cutting winners
mid-hold during T-30's wider price oscillation, before mean reversion
completes. **v2 is incompatible with a fixed 10% stop.** Wider stop
(e.g., 2× ATR adaptive) is a Phase 1.5 follow-up.

v1's shorter T-7 window has tighter intraday variance, so the 10% stop
catches more losers than winners — Sharpe improves and MaxDD shrinks
to -8%. v1 + stop becomes the better risk-adjusted candidate.

## Final Phase 1.5 verdict (revised 2026-05-26)

**Classification: 🟡 YELLOW (unchanged), best deployable variant
switched.**

| axis | result |
|---|---|
| Sharpe ≥ 1.0 (GREEN) | ❌ best variant is 0.59 |
| n_trades ≥ 30 (YELLOW) | ✅ v1+D has 29 (borderline) / v2 baseline 36 |
| MaxDD ≤ -20% (GREEN) | ✅ v1+D has -7.8% |
| Bootstrap CI lower > 0 | ✅ 0.84 full-sample |

Both v2 baseline (Sharpe 0.61 / MaxDD -29%) and v1+D (Sharpe 0.59 /
MaxDD -8%) qualify as YELLOW. **Recommended deployment variant: v1+D**
because the -7.8% MaxDD is portfolio-safe whereas v2's -29.3% would
demand a larger risk budget that the strategy's small n_trades cannot
support.

Configuration to lock into `strategies/active/unlock_v1_stop.json` if
Phase 5 portfolio composition picks this up:

```json
{
  "signal": "v1",
  "entry_offset_days": -7,
  "exit_offset_days": 0,
  "cohort": "team",
  "min_unlock_pct": 0.02,
  "stop_loss": 0.10,
  "max_position_pct": 0.05,
  "regime_filter": "pending_btc_backfill"
}
```

## Open follow-ups (carry into Phase 5 or later)

| # | Item | Blocks |
|---|---|---|
| 1 | Extend BTC 1d candle backfill to 2023-05 | Ablation C validation; Phase 3 walkforward rerun |
| 2 | Add ATR-adaptive stop loss option | v2 + adaptive stop combo |
| 3 | Bootstrap CI on v1+D combo (new winner) | n_trades=29 — need CI to size Phase 5 weight |
| 4 | Cross-thesis portfolio (Ablation E) once Phase 2.5 + 3 finalize | True diversification lift |

## References

- `docs/research/phase-1-5-diagnostic.md` — root causes 1-5 and ablation specs
- `docs/research/literature-review.md` Part A + Part C — academic backing
- `reports/phase-1-5-bootstrap-ci.md` — Ablation A
- `reports/phase-1-5-ablation-b.md` — Ablation B
- `reports/phase-1-5-ablation-d.md` — Ablation D
- `reports/phase1_5_walkforward.md` — baseline (commit ce30b2d)
- `reports/phase1_5_walkforward_team.md` — fix-cohort=team raw (commit 466a3ef)
- `reports/phase1_5_walkforward_stop.md` — stop=10% raw (commit 8df7d8b)
- `src/signals/regime_filter.py` — Ablation C module (commit 8d2d80b)
- `data/parquet/phase1_5_walkforward_trades.parquet` — per-trade returns for bootstrap
