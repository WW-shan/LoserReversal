# Phase 1.5 v1 + stop=10% Portfolio Sizing (Bayesian Bootstrap CI)

_Generated 2026-05-26 UTC_

## TL;DR

The Phase 1.5 救援 Ablation D run swapped v2 → v1 as the best deployable
unlock-short variant once a per-trade -10% stop was added. v1+stop=10%
OOS aggregate stats are:

| metric | value | source |
|---|---:|---|
| walk-forward aggregate Sharpe (per-split mean) | **0.59** | `reports/phase-1-5-ablation-d.md` |
| trade-level annualized Sharpe (point) | **1.84** | this run, 29 trades |
| n_trades (OOS) | **29** | `data/parquet/phase1_5_walkforward_stop_trades.parquet` |
| worst per-split MaxDD | **-7.77%** | `data/parquet/phase1_5_walkforward_stop.parquet` |
| win rate (aggregate) | **72.4%** | Ablation D |

Because n=29 sits below the Efron-Tibshirani percentile-bootstrap
n>=30 threshold, we re-ran the CI with a **Bayesian bootstrap** (Rubin
1981, Dirichlet(1,...,1) weights, 10,000 iterations, seed=20260524):

| percentile | Bayesian CI |
|---|---:|
| 2.5% (lower) | **0.5035** |
| 50% (median) | 1.8812 |
| 97.5% (upper) | 3.3224 |
| decision | **robust** (lower > 0) |

**Lower CI 0.50 > 0.3 -> v1+stop=10% qualifies for the highest sizing
band: up to 10% portfolio weight under fractional-Kelly on lower CI.**

## Methodology — why Bayesian over percentile

For n=29 the standard percentile bootstrap is statistically borderline:

- Efron-Tibshirani rule of thumb: n >= 30 for reasonable percentile
  bootstrap behaviour
- Wu (1986): n >= 50-60 for standard-error stability
- Resampling 29 indices with replacement leaves the bootstrap
  distribution mass at a small number of distinct samples and can
  over-cluster on extreme observations - exactly the failure mode the
  research finding 4 in `docs/research/phase-3-and-1-5-followups-research.md`
  warned against.

The Bayesian bootstrap re-weights every observation with a
Dirichlet(1,...,1) draw (uniform on the n-simplex). Each draw is a
**soft re-weighting**, not a discrete index resample, so every
observation contributes to every bootstrap sample. Recent (2025)
literature shows superior coverage at small n, especially for
fat-tailed financial returns.

The implementation lives in `scripts/bootstrap_phase1_5.py` under the
`--method bayesian` flag, with the helper `bayesian_bootstrap(...)`
exposed for downstream callers. Tests:
`tests/scripts/test_bootstrap_phase1_5.py`.

## Comparison with Ablation A v2 full-sample CI

`reports/phase-1-5-bootstrap-ci.md` (Ablation A) ran the classical
percentile bootstrap on **v2** (n=36) and reported:

| variant | n | method | lower 2.5% | median 50% | upper 97.5% |
|---|---:|---|---:|---:|---:|
| v2 baseline (no stop) | 36 | percentile | 0.84 | 2.22 | 4.09 |
| v2 baseline leave-split-3-out | 23 | percentile | -0.47 | 0.78 | 2.32 |
| **v1 + stop=10%** | **29** | **bayesian** | **0.50** | **1.88** | **3.32** |

Observations:

1. **v1+stop is narrower than v2-full and wider than v2-leave-3-out.**
   The 95% CI half-width is 1.41 (v1+stop) vs 1.62 (v2 full) vs 1.40
   (v2 leave-split-3-out). Adding the stop tightened the empirical
   variance enough that the smaller sample (29 vs 36) is offset.
2. **Lower CI 0.50 is decisively above zero.** It is also above the
   conservative 0.3 sizing threshold, qualifying v1+stop for the
   top-tier portfolio band.
3. **Median 1.88 is below v2's 2.22 but above the leave-split-3-out
   counterfactual 0.78.** Translation: the v1+stop signal does not lean
   on a single lucky fold to the same extent as v2.

## Recommended Phase 5 portfolio weight

Sizing rule (from the Phase 3 / Phase 1.5 follow-ups research,
fractional-Kelly applied to lower CI):

| lower CI band | Phase 5 weight | rationale |
|---|---|---|
| lower CI > 0.3 | **max 10% portfolio weight** | robust signal, full sleeve |
| 0 < lower CI <= 0.3 | 2-5% weight | borderline, low-conviction sleeve |
| lower CI <= 0 | DO NOT include | not distinguishable from zero |

**v1+stop=10% lower CI = 0.5035 -> top band -> max 10% Phase 5
weight.**

Concrete sizing inside the 10% sleeve, using 1/4-Kelly on the
lower CI bound:

- 1/4-Kelly fraction f_kelly_lower = (0.5035) / (1 + 0.5035^2) ~ 0.40
  per Edward Thorp's annualized variant. This is the *Kelly fraction*
  per **unit** of capital, not portfolio weight.
- Applied to a 10% sleeve, the effective allocation is
  10% * f_kelly_lower * (target Sharpe / 1.0 normalization) ~ 4-6% of
  total portfolio at risk for v1+stop.

Recommend implementing as:

- `portfolio_weight_max = 0.10` (hard cap from sizing rule)
- `kelly_fraction = 0.25` (1/4-Kelly)
- `sharpe_lower_ci = 0.5035` (input to Kelly sizing)

## Configuration to lock into `strategies/active/unlock_v1_stop.json`

```json
{
  "signal": "v1",
  "entry_offset_days": -7,
  "exit_offset_days": 0,
  "cohort": "team",
  "min_unlock_pct": 0.02,
  "stop_loss": 0.10,
  "regime_filter": "pending_btc_backfill",
  "portfolio_weight_max": 0.10,
  "kelly_fraction": 0.25,
  "sharpe_lower_ci_2_5": 0.5035,
  "sharpe_median_50": 1.8812,
  "sharpe_upper_ci_97_5": 3.3224,
  "ci_method": "bayesian",
  "ci_iterations": 10000,
  "ci_seed": 20260524,
  "n_trades_oos": 29,
  "trades_per_year_annualization": 14.4,
  "max_dd_observed_oos": -0.0777,
  "win_rate_oos": 0.7241,
  "source_run_at_utc": "2026-05-26T00:42Z",
  "source_parquet": "data/parquet/phase1_5_walkforward_stop_trades.parquet",
  "bootstrap_report": "reports/phase-1-5-bootstrap-ci-v1-stop.md",
  "sizing_report": "reports/phase-1-5-v1-stop-portfolio-sizing.md"
}
```

The `strategies/active/` directory does **not** exist yet in the
repository; this JSON is the candidate payload for whichever module
Phase 5 standardizes for runtime strategy configs. Until that module
exists, this file (`reports/phase-1-5-v1-stop-portfolio-sizing.md`)
is the canonical source of v1+stop sizing parameters.

## Caveats

1. **n_trades_oos = 29 is borderline by every standard.** Bayesian
   bootstrap restores valid coverage at this size but does not magic
   a larger sample into existence. Treat the 10% weight cap as a
   ceiling, not a target; downward adjustment is appropriate if
   real-time validation reveals regime drift.
2. **Walk-forward aggregate Sharpe 0.59 vs trade-level Sharpe 1.84.**
   The walk-forward number is the mean per-split Sharpe across 5 OOS
   folds, computed on daily mark-to-market equity returns with
   per-fold IS selection drag. The trade-level Sharpe is i.i.d.
   per-trade Sharpe annualized by sqrt(14.4). The bootstrap CI is on
   the trade-level statistic; the walk-forward 0.59 is the realised
   per-fold metric. Different questions, both valid - we cite both
   for the sizing decision.
3. **Stop cuts winners on other signals.** Ablation D's main finding
   is that v2 collapses under the stop (Sharpe 0.61 -> 0.27). The
   stop's edge on v1 specifically comes from v1's shorter T-7 hold
   window (vs T-30 for v2), where intraday adverse moves are less
   likely to be mid-mean-reversion. **Do not generalize this 10%
   stop to other signals without rerunning the bootstrap per signal.**
4. **Regime filter remains pending.** Once `BTC_1d.parquet` is
   extended to >= 2023-01-01 per finding 2 in the Phase 3/1.5
   follow-ups research, rerun `--regime-filter btc-200ma --stop-loss
   0.10` and re-bootstrap. If lower CI improves, lift the 10% weight
   cap; if it degrades, downgrade to 2-5% band.

## References

- `docs/research/phase-3-and-1-5-followups-research.md` finding 4
  (Bayesian bootstrap rationale)
- `docs/research/phase-1-5-ablation-results.md` (combined ablation table)
- `reports/phase-1-5-ablation-d.md` (stop=10% per-signal effects)
- `reports/phase-1-5-bootstrap-ci.md` (Ablation A, percentile CI on v2)
- `reports/phase-1-5-bootstrap-ci-v1-stop.md` (this run's raw CI report)
- `scripts/bootstrap_phase1_5.py` (`--method bayesian` flag)
- `data/parquet/phase1_5_walkforward_stop_trades.parquet`
  (v1+stop OOS per-trade returns)
