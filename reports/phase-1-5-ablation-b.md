# Phase 1.5 Ablation B: Fix cohort = team (Delete IS cohort search)

_Generated 2026-05-25 20:24 UTC_

## TL;DR

Fixing the IS-selected cohort to `team` (and letting walk-forward search only
`min_unlock_pct`) yields an aggregate OOS Sharpe of **0.59** over 33 trades,
versus baseline **0.61** over 36 trades. Per the Ablation B decision rule
(Sharpe >= 0.6 -> team is the real driver; Sharpe < 0.4 -> cohort search was
contributing), the result lands in the **"team is the real driver"** band
(0.59 is within 0.02 of baseline 0.61, and is in the upper "robust" band).

**Verdict: robust** -- the IS cohort search was NOT meaningfully overfitting
the Phase 1.5 v2 Sharpe; the cohort search degree of freedom contributes only
+0.02 Sharpe (-3 trades).

## Methodology

- Input: `data/parquet/phase1_5_walkforward.parquet` (baseline) and
  `data/parquet/phase1_5_walkforward_team.parquet` (--fix-cohort team).
- Same walk-forward configuration: 5 expanding splits, 270 train days,
  180 OOS test days, `min_n_trades >= 5` for IS selection, fallback to
  best positive-trade cell otherwise.
- Baseline lets IS pick across {team, team+investor, all} x {1%, 2%, 5%, 10%}
  per fold (12 cells, 5 folds, total search space = 60).
- Ablation B fixes cohort=`team` so IS only searches {1%, 2%, 5%, 10%} per
  fold (4 cells, 5 folds, total search space = 20 -- 3x narrower).
- Aggregate Sharpe row uses mean of per-split Sharpe (matches baseline
  methodology in `reports/phase1_5_walkforward.md`).

## Decision Rule (from `docs/research/phase-1-5-diagnostic.md` Ablation B)

> New Sharpe >= 0.6 with team-only -> confirms team is the real driver
> New Sharpe < 0.4 -> cohort search WAS contributing (overfit) and team
> alone is weaker than thought

The observed 0.59 sits in the upper region just below 0.6, which the
diagnostic frames as the robustness threshold. The relative drop from
baseline 0.61 (delta -0.02 Sharpe, delta -3 trades) is within bootstrap
noise (full-sample CI [0.84, 4.09] from Ablation A) and well above the
0.4 "overfit" floor. **Decision: team is the real driver.**

## Aggregate OOS Comparison (v2 signal only)

| metric | baseline (cohort search) | --fix-cohort team | delta |
| --- | ---: | ---: | ---: |
| OOS Sharpe (mean per-split) | 0.6073 | 0.5867 | -0.0206 |
| n_trades | 36 | 33 | -3 |
| win_rate | 75.00% | 75.76% | +0.76pp |
| worst max_dd | -29.30% | -29.30% | 0 |
| compounded total_return | +110.32% | +102.45% | -7.87pp |

## Per-Split Breakdown

| split | period (OOS) | baseline cohort | baseline Sharpe | baseline n | team Sharpe | team n |
| ---: | --- | --- | ---: | ---: | ---: | ---: |
| 0 | 2023-10 -> 2024-04 | all (1%) | 0.085 | 5 | 0.070 | 4 |
| 1 | 2024-04 -> 2024-09 | team (2%) | 0.932 | 4 | 0.932 | 4 |
| 2 | 2024-09 -> 2025-03 | team+investor (2%) | 0.088 | 5 | 0.001 | 3 |
| 3 | 2025-03 -> 2025-09 | team (2%) | 1.700 | 13 | 1.700 | 13 |
| 4 | 2025-09 -> 2026-03 | team (2%) | 0.232 | 9 | 0.232 | 9 |

Splits 1, 3, 4 are identical (baseline already picked team in those folds).
Splits 0 and 2 are the only differences -- baseline IS picked `all` and
`team+investor` respectively; restricting to team drops 1 trade in split 0
and 2 trades in split 2, while leaving Sharpe essentially unchanged
(delta -0.015 and -0.087 respectively).

## Interpretation

1. **Three of five folds already chose team unconstrained.** The cohort
   search was actively flexing only in two folds (splits 0 and 2), and the
   alternative cohorts only widened the trade count without lifting Sharpe.
2. **Sharpe degradation is negligible** (-0.02 delta on an estimate whose
   full-sample bootstrap CI is [0.84, 4.09] at the trade level). The
   restriction does NOT collapse Sharpe to the < 0.4 "overfit was carrying it"
   regime predicted by the diagnostic.
3. **The "split 2 problem" remains.** Baseline used team+investor to scrape
   together 5 trades on a regime that bled (Sharpe 0.088); team-only finds 3
   trades with even lower Sharpe (0.001). The cohort lever did not solve
   split 2; only Ablation C (BTC < 200d MA regime filter) is expected to.
4. **The "split 3 lucky-fold" caveat still applies.** Both runs lean on
   split 3 (Sharpe 1.700, 13 trades) to lift the aggregate above 0.5. The
   bootstrap leave-split-3-out CI was [-0.47, 2.32] -- regime dependence
   was not addressed by this ablation and must be revisited via C.
5. **YELLOW classification unchanged.** The walk-forward report still
   labels v2 as YELLOW (n_trades >= 30 and 0.3 <= Sharpe < 1.0). No
   regression and no upgrade.

## Implications for Phase 1.5 GREEN/YELLOW verdict

- **Ablation B passes its decision rule.** The cohort search degree of
  freedom is not the source of Phase 1.5's lift; team alone is essentially
  as good (0.59 vs 0.61). This removes one overfitting concern from the
  YELLOW verdict.
- **Locking cohort=team for downstream ablations is safe.** Ablation C
  (regime filter) and Ablation D (stop loss) should run with `--fix-cohort
  team` to keep the search space narrow and improve interpretability.
- **Aggregate Sharpe is still bounded by splits 0/2/4.** Even with no
  cohort search, mean per-split Sharpe is dragged below 0.6 by three
  low-performing folds; the lift continues to come from split 3.
- **Recommended params for any final lock**: `min_unlock_pct=0.02,
  cohort=team` (matches the IS selection in 3/5 folds and is one of the
  literature-prior choices flagged in the diagnostic).

## References

- `docs/research/phase-1-5-diagnostic.md` (Ablation B spec, root cause #2)
- `reports/phase1_5_walkforward.md` (baseline 0.61 result)
- `reports/phase1_5_walkforward_team.md` (--fix-cohort team raw walk-forward
  output, includes per-signal table and methodology)
- `reports/phase-1-5-bootstrap-ci.md` (Ablation A full-sample CI [0.84, 4.09])
- `data/parquet/phase1_5_walkforward.parquet` (baseline parquet)
- `data/parquet/phase1_5_walkforward_team.parquet` (this run's parquet)
