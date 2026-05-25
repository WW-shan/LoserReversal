# Phase 1.5 Ablation D: Per-Trade -10% Stop Loss

_Generated 2026-05-25 20:40 UTC_

## TL;DR

Adding a per-trade `sl_stop=0.10` to the Phase 1.5 walk-forward run brings
v2 aggregate worst MaxDD from **-29.30%** down to **-20.05%**, but at the
cost of dropping aggregate Sharpe from **0.6073** to **0.2660** (delta
**-0.3414**) and win-rate from **75.00%** to **47.37%** (delta **-27.63
pp**). Per the diagnostic's decision rule:

> New MaxDD <= 20% -> GREEN-eligible on drawdown axis
> Sharpe shouldn't drop more than 0.1 (stop cuts long-tail winners + losers
> symmetrically)

The MaxDD result lands at -20.05% (just **2 bps over** the -20% threshold)
and the Sharpe drop of -0.34 blows past the **0.1 tolerance** by 3.4x.

**Verdict: REJECT a static -10% stop on Phase 1.5 v2.** The stop cuts more
winners than losers because the contrarian unlock short relies on a
volatility regime that includes 15-25% recovery legs before the unlock
mean-reversion completes. The drawdown was reduced but not below the
threshold, and the Sharpe collapse is the dominant signal.

## Methodology

- Input parquets:
  - `data/parquet/phase1_5_walkforward.parquet` (baseline, no stop)
  - `data/parquet/phase1_5_walkforward_stop.parquet` (this run,
    `--stop-loss 0.10`)
- Identical walk-forward configuration: 5 expanding splits, 270 train
  days, 180 OOS test days, `min_n_trades >= 5` for IS selection, fallback
  to best positive-trade cell otherwise, full 12-cell IS search across
  {team, team+investor, all} x {0.01, 0.02, 0.05, 0.10}.
- The stop is wired into vbt via `BacktestConfig.stop_loss` -> the
  `sl_stop` argument of `vbt.Portfolio.from_signals`. With daily candles
  the stop fires at the bar close on the first day the running price has
  moved >= 10% against the entry, so the realised stop loss can overshoot
  -10% in fast moves.
- IS selection runs **with the stop active**, so the IS-selected
  cohort/min_pct can differ from baseline. Splits 2 in particular swapped
  cohort from `team+investor` to `all` once losses were truncated by the
  stop.

## Decision Rule (from `docs/research/phase-1-5-diagnostic.md` Ablation D)

> New MaxDD <= 20% -> GREEN-eligible on drawdown axis
> Sharpe shouldn't drop more than 0.1 (stop cuts long-tail winners + losers
> symmetrically)

Two axes need to be satisfied. Observed:

- MaxDD axis: **-20.05%** (vs -29.30%). **Fails** at -20% threshold by
  5 bps (worst single split is split 4 at -20.05%; the aggregate is
  reported as the worst per-split MaxDD).
- Sharpe axis: drop **-0.3414** (vs tolerance -0.1). **Fails** by 3.4x.

Either failure alone would block GREEN; both together make the verdict
unambiguous.

## Aggregate OOS Comparison (v2 signal only)

| metric                       | baseline (no stop) | stop=10% | delta      |
| ---------------------------- | -----------------: | -------: | ---------: |
| OOS Sharpe (mean per-split)  |             0.6073 |   0.2660 |    -0.3414 |
| n_trades                     |                 36 |       38 |         +2 |
| win_rate                     |             75.00% |   47.37% |   -27.63pp |
| worst max_dd                 |            -29.30% |  -20.05% |     +9.25pp |
| compounded total_return      |           +110.32% |  +25.22% |    -85.10pp |

## Per-Split Breakdown (v2 signal)

| split | OOS window        | base cohort      | base Sharpe | base n | base MaxDD | stop cohort | stop Sharpe | stop n | stop MaxDD |
| ----: | ----------------- | ---------------- | ----------: | -----: | ---------: | ----------- | ----------: | -----: | ---------: |
| 0     | 2023-10 -> 2024-04 | all              |       0.085 |      5 |    -17.51% | all         |      -0.335 |      5 |    -16.71% |
| 1     | 2024-04 -> 2024-09 | team             |       0.932 |      4 |     -5.73% | team        |       0.578 |      4 |     -5.65% |
| 2     | 2024-09 -> 2025-03 | team+investor    |       0.088 |      5 |    -21.00% | all         |      -0.622 |      7 |    -17.70% |
| 3     | 2025-03 -> 2025-09 | team             |       1.700 |     13 |     -5.63% | team        |       1.652 |     13 |     -5.94% |
| 4     | 2025-09 -> 2026-03 | team             |       0.232 |      9 |    -29.30% | team        |       0.058 |      9 |    -20.05% |

Notes:

- Splits 0, 1, 3, 4 kept the same IS-selected cohort/min_pct.
- Split 2 switched from `team+investor` to `all` because once the stop
  caps the worst trades, the broader cohort's larger sample size becomes
  the marginally better IS Sharpe candidate. The OOS Sharpe of the `all`
  cohort in this period is -0.62 versus baseline `team+investor` at
  +0.09, so the IS lever made the OOS result worse here.
- Split 4 is the headline drawdown fold (bear-period failure described in
  diagnostic root cause #3). The stop trimmed MaxDD from -29.30% to
  -20.05% (-9.25pp) but also flattened Sharpe from 0.232 to 0.058, so the
  protection came at near-total loss of OOS edge in that fold.

## Interpretation

1. **Stop cuts winners more than losers.** v2 win-rate falls from 75%
   to 47%. That is the structural problem: an unlock short that runs
   against the trade for 10% is **inside its typical hold envelope**.
   Tokens often rip 10-15% on positioning before unwinding into the
   unlock; a fixed -10% stop forces an exit right at the squeeze top, on
   trades that would have closed flat-to-positive at expiry.
2. **MaxDD reduction is real but insufficient.** The aggregate worst
   MaxDD is the worst-per-split aggregate (split 4 again). The stop
   reduced split 4 from -29% to -20%, but worse-tier splits stayed
   roughly the same drawdown. The -20.05% number is at the threshold by
   construction (`sl_stop=0.10` on a single trade caps a single trade
   loss near -10%, but stacked open positions can compound, and bear
   regimes still bleed).
3. **IS cohort search adds variance under the stop.** Split 2 swapped
   cohort because the stop changes the OOS-vs-IS ranking. Combining
   Ablation D with Ablation B (fix cohort=team) would reduce this
   stochastic flip, but it would not fix the Sharpe collapse on splits
   0, 1, 4 (which already used team).
4. **All other signals lose Sharpe too.** v1 is the only mild winner
   (0.47 -> 0.59); v3 holds, v4 mostly holds, v5 drops below zero
   (0.06 -> -0.18). The stop is destructive on every contrarian short
   except v1 (T-7 window, shortest hold time and tightest entry / exit
   thesis); even there the lift is within bootstrap noise.
5. **Portfolio level: same story.** top_2 equal-weight Sharpe drops
   0.54 -> 0.43 with MaxDD improving -17% -> -12%. The trade is
   protective on drawdown but expensive on edge.

## Implications for Phase 1.5 GREEN/YELLOW verdict

- **Ablation D fails its decision rule.** A static -10% stop does not
  upgrade v2 toward GREEN; MaxDD lands at the threshold, Sharpe collapses
  past tolerance.
- **Static stops are the wrong instrument for this thesis.** The next
  natural attempt would be an **event-conditional** stop (wider stop
  before the unlock, tighter stop after) or an **ATR-scaled** stop that
  adapts to volatility. The diagnostic's Q3 citation explicitly mentions
  "event-specific buffers (5-10%) around news"; the **fixed** -10% read
  here is the conservative inner bound and is too tight.
- **Ablation C (regime filter) remains the more promising path.** Split
  4 (-29% baseline -> -20% with stop) is the bear-period rally failure
  pointed at by root cause #3. A BTC-200d-MA filter that gates out the
  squeeze rallies would address the source rather than mask the symptom.
- **No-stop baseline stays the reference.** Phase 1.5 v2 stays YELLOW
  on Sharpe (0.61, n=36) and RED on drawdown (-29%). Ablation D does not
  resolve the drawdown axis without sacrificing the Sharpe axis.
- **Recommended next step**: combine Ablation B (`--fix-cohort team`)
  + Ablation C (regime filter) and re-evaluate; only if MaxDD remains
  >20% after C should a stop be re-attempted, and that next attempt
  should be **ATR-scaled** rather than a flat fraction.

## References

- `docs/research/phase-1-5-diagnostic.md` (Ablation D spec, root cause #4)
- `reports/phase1_5_walkforward.md` (baseline 0.61 / -29% MaxDD)
- `reports/phase1_5_walkforward_stop.md` (this run's full walk-forward
  output, includes all five signals' per-split tables)
- `reports/phase-1-5-ablation-b.md` (cohort=team ablation, complementary)
- `data/parquet/phase1_5_walkforward.parquet` (baseline parquet)
- `data/parquet/phase1_5_walkforward_stop.parquet` (this run's parquet)
- `src/infra/backtest/engine.py` (BacktestConfig.stop_loss -> vbt sl_stop)
