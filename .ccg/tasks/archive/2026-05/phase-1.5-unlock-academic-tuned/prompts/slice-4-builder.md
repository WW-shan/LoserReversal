ROLE_FILE: /Users/ww/.claude/.ccg/prompts/codex/builder.md

# Phase 1.5 Slice 4 — Walk-forward + Multi-signal Portfolio

## CRITICAL: Anti-monitor directive

- Do NOT tail/ps/grep for other codex processes. Start writing code IMMEDIATELY.
- Other codex processes belong to the user; UNRELATED to this task.
- Do NOT archive this task. Claude will archive after final LGTM.

## Working directory
`/Users/ww/Project/crypto-alpha-portfolio`

`uv run`, Python 3.11+, 100-char lines, UTC tz-aware, no emojis.

## Required reading

- `.ccg/tasks/phase-1.5-unlock-academic-tuned/plan.md` Slice 4 spec
- `src/infra/backtest/walkforward.py` (existing helper)
- `src/signals/unlock_grid.py` (registry + run_cell)
- `scripts/sweep_unlock_grid_v15.py` (grid sweep CLI — reuse loaders + plumbing)
- `scripts/run_unlock_walkforward.py` (v1-only walk-forward — reference for structure)
- `data/parquet/unlock_grid_v15.parquet` (IS rankings already known)

## Slice 3 takeaways (use as priors for Slice 4)

- **v1 dominates**: top 5 IS Sharpe cells are all v1 (T-7 short)
- **Best cell**: v1 / 2% / team — IS Sharpe 1.60, n_trades 47, win_rate 76.6%
- v2 next; v3/v4/v5 underperform IS
- vesting cliff > step > linear

## Goal of this slice

Walk-forward validation + multi-signal portfolio composition:

1. **Walk-forward per signal**: For each of the 5 signals separately, run 3 expanding splits and report OOS Sharpe / n_trades / win_rate per fold + aggregate.
2. **Multi-signal portfolio**: Combine v1+v2 (or top-N signals by IS Sharpe) into a single weighted portfolio. Re-run walk-forward on the combined strategy.
3. **Pass/Kill verdict prep**: emit a structured `phase1_5_walkforward.parquet` so Slice 5 can read it to render the final report.

## Specifications

### Walk-forward config (defaults)
- `n_splits = 3` (matches Phase 2 precedent)
- `mode = "expanding"`
- `min_train_days = 180` (6 months — gives enough team-cohort events per fold)
- `test_days = 90` (3 months OOS)
- If the time range is too short, automatically reduce `test_days` to 60 then 30 with a warning (fallback per Phase 1/2 precedent)

### Per-signal walk-forward
For each signal in `SIGNAL_REGISTRY`:
- For each split (train_window, test_window):
  - Use TRAIN window events to "select" the best (min_pct, cohort) for that signal via IS Sharpe — pick top eligible cell (n_trades ≥ 15 in train, lower than main grid threshold)
  - Apply that config to TEST window events
  - Backtest OOS, record n_trades, sharpe, win_rate, max_dd
- Aggregate: mean OOS Sharpe across splits, total OOS n_trades, OOS win_rate

### Multi-signal portfolio
- Select top-K signals (default K=2) by aggregate OOS Sharpe across folds
- For each split:
  - For each selected signal, generate train-tuned config
  - Run OOS, get equity series
  - Combine equity with equal weights (1/K) OR risk-parity (vol_target weight ∝ 1/realized_vol_train)
  - Aggregate stats: combined Sharpe, n_trades sum, combined max_dd, combined total_return
- Save per-split combined equity series for visualization

### Output schemas

`data/parquet/phase1_5_walkforward.parquet` columns:
- `kind: string` (`per_signal` | `portfolio`)
- `signal: string` (v1..v5 for per_signal; `top_K_equal_weight` for portfolio)
- `split_idx: int` (0..n_splits-1, or -1 for aggregate)
- `train_start: timestamp[us, UTC]`
- `train_end: timestamp[us, UTC]`
- `test_start: timestamp[us, UTC]`
- `test_end: timestamp[us, UTC]`
- `selected_min_pct: float64`
- `selected_cohort: string`
- `n_trades: int64`
- `sharpe: float64`
- `sortino: float64`
- `win_rate: float64`
- `max_dd: float64`
- `total_return: float64`
- `fallback_used: bool` (true if test_days was reduced to fit)

`reports/phase1_5_walkforward.md`:
- Methodology (mirror Slice 3 fix style)
- Per-signal table: rows = signals, cols = mean OOS Sharpe, total n_trades, mean win_rate, mean max_dd, IS-vs-OOS decay
- Portfolio table: top-K with combined Sharpe, n_trades
- Best-signal verdict snapshot: signal name + OOS Sharpe + n_trades

## Scope (file list)

### Create
- `src/signals/unlock_walkforward.py`:
  - `select_best_config(grid_df, signal_code, train_events, train_prices, train_coverage, min_n_trades=15) -> GridCell | None`
    - Re-runs each (min_pct, cohort) cell within the signal on the train slice → picks highest-Sharpe with `n_trades >= min_n_trades`
  - `run_per_signal_walkforward(events, prices, coverage, splits, signals_to_run) -> pd.DataFrame`
  - `compose_portfolio(per_signal_df, events, prices, coverage, splits, top_k=2) -> pd.DataFrame`
- `scripts/run_unlock_walkforward_v15.py`:
  - CLI args: `--n-splits`, `--mode`, `--min-train-days`, `--test-days`, `--top-k`, `--out`, `--report`, `--init-cash`, `--fees`, `--slippage`
  - Loads `unlocks.parquet` + `event_coverage.parquet` + `candles/*_1d.parquet`
  - Calls `walk_forward_splits` then `run_per_signal_walkforward` then `compose_portfolio`
  - Writes parquet + markdown report
- `tests/signals/test_unlock_walkforward.py`
  - `test_select_best_config_returns_highest_sharpe_eligible`
  - `test_select_best_config_returns_none_when_no_eligible`
  - `test_run_per_signal_walkforward_yields_one_row_per_signal_per_split` (with mocked run_cell)
  - `test_run_per_signal_walkforward_includes_aggregate_row` (with mocked run_cell)
  - `test_compose_portfolio_equal_weights_K2` (with mocked run_cell)
- `tests/scripts/test_run_unlock_walkforward_v15.py`
  - `test_cli_smoke` (mock heavy backtests, assert CLI exits 0 + parquet + report written)
  - `test_cli_falls_back_to_shorter_test_days_when_range_too_short`

### Modify
- Nothing in Slice 1/2/3 frozen modules

## Workflow (strict TDD)

Expected commits (~12):

1. `test(signals): walkforward select_best_config cases`
2. `feat(signals): walkforward per-signal config selector`
3. `test(signals): walkforward per-signal runner`
4. `feat(signals): walkforward per-signal runner`
5. `test(signals): walkforward portfolio compose top-K equal-weight`
6. `feat(signals): walkforward portfolio compose top-K equal-weight`
7. `test(scripts): walkforward v15 CLI smoke`
8. `feat(scripts): walkforward v15 CLI`
9. `test(scripts): walkforward v15 fallback to shorter test window`
10. `feat(scripts): walkforward v15 fallback handling`
11. (real-data) `chore(data): refresh phase1.5 walkforward parquet + report`

After each commit:
- `uv run pytest -q` ≥ previous count
- `uv run ruff check src tests scripts data` clean

Target: 285 → ~300 tests.

## Acceptance

- `data/parquet/phase1_5_walkforward.parquet` exists with both `per_signal` and `portfolio` rows
- `reports/phase1_5_walkforward.md` exists with Methodology + per-signal table + portfolio table + best-signal snapshot
- pytest ≥ 300
- ruff clean
- ~10-12 small commits, no monolithic commit

## Out-of-scope guardrails

Do NOT:
- Compute the final Pass/Kill verdict (Slice 5)
- Update ROADMAP.md (Slice 5)
- Modify Slice 1/2/3 frozen code
- Add new signal modules
- Push to GitHub

## Completion

```
## Execution Report — Slice 4

### Files touched
- ...

### Commits
- ...

### Pytest / Ruff
- baseline: 285
- final: {N}
- ruff: clean

### Walk-forward results
- Per-signal best aggregate OOS Sharpe:
  | signal | mean OOS Sharpe | total OOS n_trades | mean OOS win_rate | IS-vs-OOS decay |
  ...

- Portfolio (top-K equal-weight):
  - K={N}, signals = {...}
  - Aggregate OOS Sharpe = {X}
  - Total OOS n_trades = {N}

- Pass/Kill prep: best signal {name} OOS Sharpe = {X}, n_trades = {N}
```

EXIT. Do NOT archive. Do NOT push.
