# Phase 1.5 Rescue Ablations (A/B/C/D) — Plan

> Reading the diagnostic: `docs/research/phase-1-5-diagnostic.md`
> Reading the literature: `docs/research/literature-review.md` Part C (dr-1 … dr-6)
> Parent verdict: Phase 1.5 v2 (T-30→T0 short) OOS Sharpe **0.61**, n_trades **36**, MaxDD **-29%**, win 75% → 🟡 YELLOW
> Goal: run 4 academic-validated ablations to decide GREEN / accept-YELLOW / RED.

## Context

Phase 1.5 verdict was YELLOW. Diagnostic identified 5 root causes:

1. Split 3 lucky-fold carrying mean (Sharpe 1.70 on 13 trades)
2. IS cohort selection drifts across splits (team / team+investor / all)
3. Bear-period failure on Split 4 (Sharpe 0.23, MaxDD -29%)
4. MaxDD -29% exceeds GREEN threshold (-20%)
5. v1+v2 portfolio Sharpe (0.54) < v2 alone (0.61) — correlation drag

Ablations A/B/C/D each target one or more root causes. E (cross-thesis portfolio) is deferred to Phase 5 after Phase 3 + Phase 2.5 verdicts.

## Multi-model analysis source

Analysis is already captured in:
- `docs/research/phase-1-5-diagnostic.md` — 5 root causes + 4 ablation specs with academic citations (dr-1 through dr-6 deep research)
- `docs/research/literature-review.md` Part C — academic backing for each ablation

This is the analysis output from the YELLOW verdict review; no additional Codex Phase-3-analysis call required beyond the existing literature trail.

## Ablations

### Ablation A — Bootstrap CI on v2 OOS Sharpe

**Purpose**: tell whether 0.61 Sharpe is robust or lucky-fold artifact (root cause #1).

**Method**:
1. Load v2 OOS rows from `data/parquet/phase1_5_walkforward.parquet`
2. Extract per-trade return series (36 trades)
3. Resample with replacement 10,000 times
4. Compute Sharpe per bootstrap sample
5. Report 2.5% / 50% / 97.5% percentiles + sample mean

**Decision rule**:
- 2.5% percentile > 0 → signal is **robust** — proceed with B/C/D
- 2.5% percentile < 0 → likely lucky-fold — accept YELLOW or downgrade

**Files**:
- `scripts/bootstrap_phase1_5_v2.py`
- `tests/scripts/test_bootstrap_phase1_5_v2.py`
- `data/parquet/phase1_5_bootstrap_v2.parquet`
- `reports/phase1_5_ablation_A_bootstrap.md`

**Cost**: ~1h

### Ablation B — Fix cohort = team (delete IS lookahead)

**Purpose**: quantify how much of 0.61 came from per-fold cohort search (root cause #2).

**Method**:
1. Add `--fix-cohort` flag to `scripts/run_unlock_walkforward_v15.py` (and propagate through `src/signals/unlock_walkforward.py`)
2. Rerun walk-forward with `cohort=team` fixed across all 5 splits (IS still selects min_pct only)
3. Compare aggregate Sharpe vs current 0.61

**Decision rule**:
- New Sharpe ≥ 0.6 with team-only → cohort drift was not the main source of alpha (signal robust)
- New Sharpe < 0.4 → cohort search was contributing (overfit) — accept lower YELLOW

**Files**:
- Modify: `src/signals/unlock_walkforward.py` — add `fix_cohort` parameter
- Modify: `scripts/run_unlock_walkforward_v15.py` — add `--fix-cohort` CLI flag
- Add: `tests/signals/test_unlock_walkforward_fix_cohort.py`
- Output: `data/parquet/phase1_5_walkforward_B_fixcohort.parquet`
- Report: `reports/phase1_5_ablation_B_fixcohort.md`

**Cost**: ~0.5d

### Ablation C — BTC < 200d MA filter (bear-only short entries)

**Purpose**: test if avoiding bull-market squeeze recovers Sharpe; specifically targets Split 4 (-29% MaxDD, recovery rally period). Root cause #3.

**Method**:
1. Compute BTC 200d SMA daily series from `data/parquet/candles/BTC_1d.parquet`
2. Add `--regime-filter btc_below_sma200` flag to walkforward CLI (and propagate filter to signal/event pipeline)
3. Filter unlock events: emit signal only when `entry_date_BTC_spot < BTC_200d_SMA(entry_date)`
4. Rerun walk-forward; compare Sharpe + MaxDD + trade count vs baseline + per-split breakdown

**Decision rule**:
- Filtered Sharpe ≥ 0.8 AND n_trades ≥ 30 → GREEN-candidate via regime filter
- Filtered Sharpe < 0.4 OR n_trades < 20 → regime hypothesis wrong; abandon
- Split 4 MaxDD should drop ≥ 10pp (was -29%); if not, filter is mis-specified

**Files**:
- Add: `src/signals/regime_filter.py` — BTC SMA filter primitive
- Modify: `src/signals/unlock_walkforward.py` — accept regime filter callable
- Modify: `scripts/run_unlock_walkforward_v15.py` — add `--regime-filter` CLI flag
- Add: `tests/signals/test_regime_filter.py`
- Add: `tests/signals/test_unlock_walkforward_regime.py`
- Output: `data/parquet/phase1_5_walkforward_C_regime.parquet`
- Report: `reports/phase1_5_ablation_C_regime.md`

**Cost**: ~1d

### Ablation D — Per-trade -10% stop loss

**Purpose**: reduce MaxDD below 20% GREEN threshold (root cause #4).

**Method**:
1. Wrap `run_backtest` to support `stop_loss=0.10` (early exit if per-trade PnL ≤ -10%)
2. Rerun walk-forward with stop active
3. Compare MaxDD + Sharpe + win_rate

**Decision rule**:
- New MaxDD ≤ 20% → GREEN-eligible on drawdown axis
- Sharpe degradation ≤ 0.1 → stop is symmetric cut, acceptable
- Sharpe degradation > 0.3 → stop is cutting too many winners; reject

**Files**:
- Modify: `src/infra/backtest/engine.py` (or wrapper) — `stop_loss` parameter
- Modify: `scripts/run_unlock_walkforward_v15.py` — `--stop-loss` flag
- Add: `tests/infra/backtest/test_engine_stop_loss.py`
- Output: `data/parquet/phase1_5_walkforward_D_stop.parquet`
- Report: `reports/phase1_5_ablation_D_stop.md`

**Cost**: ~0.5d

### Combined A+B+C+D rerun

After A/B/C/D individually:
1. Rerun walkforward with B + C + D simultaneously (skip A — it's diagnostic, not strategy)
2. Compare combined vs each individual vs baseline
3. Write `docs/research/phase-1-5-ablation-results.md`

**Decision matrix**:
- Combined Sharpe ≥ 1.0 AND MaxDD ≤ 20% → **upgrade to GREEN**, lock params in `strategies/active/unlock_v2.json` (gitignored)
- Combined Sharpe ∈ [0.5, 1.0) OR MaxDD > 20% → **accept YELLOW**, include in Phase 5 as low-weight component
- Combined Sharpe < 0.3 OR A failed (CI lower < 0) → **downgrade to RED**, exclude from Phase 5

**Files**:
- `data/parquet/phase1_5_walkforward_combined.parquet`
- `docs/research/phase-1-5-ablation-results.md` (final comparison)
- Update: `docs/research/status-snapshot.md` Phase 1.5 row
- Update: `docs/research/loser-reversal-indicator/ROADMAP.md` Phase 1.5/1.6 section

## Slice ordering

Recommended sequential execution (some can run in parallel — see Execution Mode):

| Slice | Ablation | Cost | Depends on |
|---|---|---|---|
| **0** | **Prereq: extend walkforward to record per-trade returns** | **~0.5d** | **nothing (discovered 2026-05-25)** |
| 1 | A — Bootstrap CI | 1h | Slice 0 (needs per-trade parquet) |
| 2 | B — Fix cohort | 0.5d | nothing |
| 3 | C — Regime filter | 1d | nothing |
| 4 | D — Stop loss | 0.5d | nothing |
| 5 | Combined + final verdict report | 0.5d | 1-4 done |

A blocks nothing — its result informs whether B/C/D are worth running, but they can pre-load in parallel.

### Slice 0 — Prerequisite (added 2026-05-25)

**Discovered**: `data/parquet/phase1_5_walkforward.parquet` only persists per-split aggregate rows (n_trades, sharpe, …); the 36 actual per-trade returns required for bootstrap are not stored. Codex correctly stopped per Ablation A prompt guardrail.

**Goal**: Extend `unlock_walkforward.py` + `run_unlock_walkforward_v15.py` to optionally emit a second parquet `phase1_5_walkforward_trades.parquet` with one row per OOS trade, then re-run v2 with the new flag.

**Files**:
- Modify: `src/signals/unlock_walkforward.py` — add `record_trades: bool` parameter, accumulate per-trade rows during OOS evaluation
- Modify: `scripts/run_unlock_walkforward_v15.py` — `--record-trades` + `--trades-out PATH` flags
- Add: `tests/signals/test_unlock_walkforward_record_trades.py`
- Output: `data/parquet/phase1_5_walkforward_trades.parquet` (schema: signal, split_idx, token, entry_ts, exit_ts, direction, return, hold_days, win)

**Pass criteria**:
- v2 OOS rows in new parquet sum to 36 (matches existing aggregate count)
- Aggregate Sharpe reconstructed from per-trade returns matches existing 0.61 within 1e-4

**Execution note (2026-05-25)**: Slice 0 implementation landed with optional
`record_trades` plumbing and seeded `data/parquet/phase1_5_walkforward_trades.parquet`.
The new parquet records raw vectorbt closed-trade returns post fees/slippage; v2 row count
matches the existing aggregate (`36`). The Sharpe reconstruction criterion remains a metric-basis
caveat: the existing aggregate Sharpe is computed from daily equity returns, not per-trade
returns, so raw trade returns do not reconstruct `0.607335` without changing the metric basis.

## Pass criteria (whole rescue task)

- A produces bootstrap CI report (always succeeds, only verdict differs)
- B, C, D each produce comparable Sharpe / MaxDD / n_trades vs baseline
- Combined report `phase-1-5-ablation-results.md` has explicit GREEN / YELLOW / RED verdict
- ROADMAP + status-snapshot updated

## Non-negotiable constraints

Same as Phase 1.5 task: TDD, 100-char, UTC, no emoji, anti-monitor, no archive by builder, three-way review per slice (Codex + subagent + Claude semantic).

## Out-of-scope guardrails

Do NOT:
- Touch any funding signal files (parallel task `phase-3-funding-arbitrage` works there)
- Re-run Phase 1.5 grid sweep (the IS phase is locked; ablations operate on walkforward only)
- Add new signal versions (v1-v5 are frozen; ablations modify hyperparams/filters, not signal shape)
