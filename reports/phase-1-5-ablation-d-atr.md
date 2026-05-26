# Phase 1.5 Ablation D — ATR-Adaptive Stop Comparison

_Generated 2026-05-26 UTC_

## Question

Can replacing the fixed 10% stop with a 2x ATR-adaptive stop recover v2
to Sharpe >= 0.5 while keeping MaxDD <= 22%?

## Result

| variant | v2 Sharpe | v2 MaxDD | v2 win rate | decision |
|---|---:|---:|---:|---|
| baseline (no stop) | 0.61 | -29.3% | 75.0% | Sharpe passes, MaxDD fails |
| fixed-10% stop | 0.27 | -20.1% | 47.4% | MaxDD passes, Sharpe fails |
| ATR-2x stop | 0.48 | -16.4% | 52.8% | MaxDD passes, Sharpe near-misses |

ATR-2x improves v2 materially over the fixed 10% stop: Sharpe rises from
0.27 to 0.48, MaxDD improves to -16.4%, and win rate recovers from 47.4%
to 52.8%. It does not fully restore the no-stop v2 Sharpe, and it misses
the recovery threshold by 0.02 Sharpe points.

## Decision

**v2+ATR does not qualify as the deployable replacement.** It satisfies
the MaxDD <= 22% requirement but misses Sharpe >= 0.5. The best ATR run
signal remains v1 at Sharpe 0.59 / MaxDD -11.0% / win rate 69.2%, which
is consistent with the earlier v1+D deployment recommendation.

## Artifacts

- `data/parquet/phase1_5_walkforward_atr.parquet`
- `reports/phase1_5_walkforward_atr.md`
