ROLE_FILE: /Users/ww/.claude/.ccg/prompts/codex/reviewer.md

# Phase 1.5 Slice 3 — Code Review

## CRITICAL: Read-only

NO write permission.

## Working directory
`/Users/ww/Project/crypto-alpha-portfolio`

## What was implemented

3-dimensional unlock grid sweep:
- 5 signals × 4 size thresholds × 3 cohorts = 60 main cells
- Plus best-cell vesting_type sub-sweep (3 extra rows)
- Real data: 1768 unlocks, 532 events with coverage data, 55 HL-perp tokens

Results:
- v1 T-7→T0, team cohort, min_pct 2% → Sharpe 1.60, n_trades 47, win_rate 76.6%, max_dd -2.7%
- v2/v3/v4/v5 all underperformed v1 (which is the SmartKarma "T-7 isn't optimal" claim being partially refuted)
- Best vesting subtype: cliff (Sharpe 1.65)

## Reading list

- `.ccg/tasks/phase-1.5-unlock-academic-tuned/prompts/slice-3-builder.md` (spec)
- `src/signals/unlock_grid.py` (registry + run_cell)
- `scripts/sweep_unlock_grid_v15.py` (CLI driver)
- `data/parquet/unlock_grid_v15.parquet` (output)
- `reports/phase1_5_grid_sweep.md` (top-5 + per-cohort)
- `tests/signals/test_unlock_grid.py`
- `tests/scripts/test_sweep_unlock_grid_v15.py`

## Commits to review

Use `git log --oneline 7db22b4..HEAD` to see Slice 3 commits.

## What to verify

### Plan alignment
- 60 main cells produced? (5 signals × 4 pct × 3 cohorts)
- Sub-sweep produces 3 vesting rows tagged by type?
- Cohorts: team / team+investor / all match spec (insiders only vs insiders+privateSale vs no filter)?
- v5 backtested as long (longonly), v1-v4 as short (shortonly)?
- Coverage filter applied via `coverage_status == 'ok'`?

### Correctness
- The Sharpe = 1.60 result — is it credible or is there a leak?
  - n_trades = 47 → ~7 trades/year over 2023-2026 (reasonable for monthly unlock cadence)
  - win_rate 76.6% on shorts during a bullish 2024-2025 period is striking — verify with `pd.read_parquet('data/parquet/unlock_grid_v15.parquet')` and look at per-token contributions
  - max_dd -2.7% only — does the trade ledger actually compound losses, or are positions sized too small?
- `run_cell` aggregation: are stats computed across all tokens correctly, or one-token-at-a-time-and-averaged?
- The vesting sub-sweep: does it correctly inherit (signal, min_pct, cohort) from the best main cell?

### Code quality
- `signal_fn` calls in `run_cell` — does it pass `coverage` AND `min_unlock_pct` correctly to each signal version (v1..v5 share signature)?
- `BacktestConfig.direction` parameter (was added if it didn't exist) — does the engine actually respect it for shortonly vs longonly?
- No data leakage (using future prices)?
- All-cohort vs team-only — is the filter set comparison correct (`category in {'insiders'}` vs `category in {'insiders', 'privateSale'}`)?

### Tests
- TDD pairs in commit log?
- `test_iter_grid_yields_60_cells` — verifies grid size?
- `test_run_cell_marks_long_direction_for_v5` — verifies v5 uses long?
- CLI integration test runs a small fixture and verifies parquet structure?

### Production readiness
- `pytest -q` ≥ 280?
- `ruff check` clean?
- The parquet schema: stable enough for Slice 4 walk-forward to consume?

## Output Format

### Strengths

### Issues

#### Critical (Must Fix)

#### Important (Should Fix)

#### Minor (Nice to Have)

### Assessment
**Ready to merge into Slice 4?** [Yes | No | With fixes]
**Reasoning:** [2-3 sentences.]
