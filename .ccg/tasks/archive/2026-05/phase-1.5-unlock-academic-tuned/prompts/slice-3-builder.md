ROLE_FILE: /Users/ww/.claude/.ccg/prompts/codex/builder.md

# Phase 1.5 Slice 3 — 3-Dimensional Grid Sweep

## CRITICAL: Anti-monitor directive

- Do NOT tail/ps/grep for other codex processes. Start writing code IMMEDIATELY.
- Other codex processes belong to the user; UNRELATED to this task.
- Do NOT archive this task. Claude will archive after final LGTM.

## Working directory
`/Users/ww/Project/crypto-alpha-portfolio`

`uv run`, Python 3.11+, `from __future__ import annotations`, 100-char lines, UTC tz-aware, no emojis.

## Required reading

- `docs/research/literature-review.md` Part A.3 (size bucket effects), A.4 (category ordering), A.5 (vesting type), A.7 (execution costs)
- `.ccg/tasks/phase-1.5-unlock-academic-tuned/plan.md` Slice 3 spec
- `src/signals/unlock_v1.py` through `unlock_v5.py` — your sweep targets
- `src/signals/_unlock_common.py` — shared filter/emit
- `src/infra/data_audit.compute_event_candle_coverage` — coverage filter (must apply)
- `src/infra/backtest/engine.py` (BacktestConfig / run_backtest)
- `src/infra/backtest/risk.py` (sharpe_ratio / sortino_ratio / max_drawdown)
- `scripts/run_unlock_backtest.py` (v1-specific backtester — reuse structure)
- `scripts/sweep_unlock_params.py` (existing 2-dim sweep — reuse output format ideas)

## Goal of this slice

A single CLI runs the **5 signals × 4 size thresholds × 3 categories** grid (= 60 cells) on real data, plus a separate cliff-vs-linear sub-sweep. Output is a parquet of per-cell stats + a markdown report.

NOT walk-forward — that's Slice 4. This slice is an IS-only grid scan to surface promising configs.

## Grid dimensions

**Signal version** (5):
| Code | Function | Direction | Entry offset days | Exit offset days |
|------|----------|-----------|-------------------|------------------|
| v1 | `unlock_short_signal` | short | -7 | 0 |
| v2 | `unlock_short_30d` | short | -30 | 0 |
| v3 | `unlock_short_tactical` | short | -2 | +3 |
| v4 | `unlock_short_72h` | short | -3 | 0 |
| v5 | `unlock_reversal_long` | long | +3 | +14 |

**Size threshold (`min_unlock_pct`)** (4): `{0.01, 0.02, 0.05, 0.10}`

**Category cohort** (3):
- `team` — events where `category in {"insiders"}` (the parser maps team→insiders + insiders→insiders)
- `team+investor` — `category in {"insiders", "privateSale"}`
- `all` — no category filter

**Sub-sweep**: cliff vs step vs linear (run only the BEST cell from the main grid for each vesting_type — produces 3 extra rows)

## Scope (file list)

### Create
- `scripts/sweep_unlock_grid_v15.py` — 3-dim grid sweep CLI
  - Args: `--out PATH` (default `data/parquet/unlock_grid_v15.parquet`), `--report PATH` (default `reports/phase1_5_grid_sweep.md`), `--init-cash FLOAT`, `--fees FLOAT`, `--slippage FLOAT`, `--date-start ISO` (default events.min), `--date-end ISO` (default events.max)
  - Loads `unlocks.parquet` + `event_coverage.parquet` + `candles/*_1d.parquet`
  - For each (signal, min_pct, category) cell:
    - Apply pct filter + category filter + coverage_status=='ok' filter
    - Call the signal function → entries/exits
    - Backtest via `infra.backtest.engine.run_backtest` (or simpler: vectorbt `Portfolio.from_signals` per token, aggregated)
    - Compute: n_trades, win_rate, sharpe, sortino, max_dd, total_return, mean_pnl, median_pnl
    - For v5: backtest as long (direction='long' in BacktestConfig — check engine API)
  - Write per-cell row to parquet
  - Print top-5 by Sharpe (eligible = n_trades ≥ 30)
- `src/signals/unlock_grid.py` — small module with helper:
  - `SIGNAL_REGISTRY: dict[str, SignalSpec]` — maps "v1".."v5" → (function, direction, default kwargs)
  - `CATEGORY_COHORTS: dict[str, set[str]]` — cohort name → category set (or `None` for "all")
  - `SIZE_THRESHOLDS: tuple[float, ...]`
  - `iter_grid()` → generator of (signal_code, min_pct, cohort_name, signal_fn, direction, category_filter)
  - `run_cell(events, prices, coverage, cell, fees, slippage, init_cash) -> dict` — single-cell runner returning stats dict
- `tests/scripts/test_sweep_unlock_grid_v15.py` — CLI integration test (mock the heavy backtest), assert per-cell row count == 60, smoke run
- `tests/signals/test_unlock_grid.py` — registry + cohort filter unit tests
  - `test_signal_registry_has_all_5_versions`
  - `test_category_cohort_team_only_keeps_insiders`
  - `test_category_cohort_team_investor_keeps_insiders_and_private_sale`
  - `test_category_cohort_all_passes_everything`
  - `test_iter_grid_yields_60_cells`
  - `test_run_cell_returns_stats_keys` (mocked prices fixture)
  - `test_run_cell_marks_long_direction_for_v5` (verify v5 backtest runs long not short)

### Modify (small additions only)
- `src/infra/backtest/engine.py` — IF the existing engine doesn't expose a `direction` ('long' | 'short') parameter, add it cleanly. If it does, no change needed. Check first.

### Out of scope
- Walk-forward (Slice 4)
- Multi-signal portfolio combination (Slice 4)
- Verdict / ROADMAP update (Slice 5)
- New backtest engines or risk metrics
- Any scraper, fetcher, parquet schema migration

## Specifications

### `run_cell`

Pseudocode:
```python
def run_cell(
    events: pd.DataFrame,
    prices: dict[str, pd.Series],
    coverage: pd.DataFrame,
    cell: GridCell,
    *,
    init_cash: float,
    fees: float,
    slippage: float,
) -> dict[str, Any]:
    # apply category filter
    filtered = events
    if cell.category_filter is not None:
        filtered = filtered[filtered["category"].isin(cell.category_filter)]
    # call signal with min_unlock_pct AND coverage
    signal_result = cell.signal_fn(filtered, prices, min_unlock_pct=cell.min_unlock_pct, coverage=coverage)
    # run backtest per-token then aggregate
    portfolio_stats = backtest_signals(prices, signal_result, cell.direction, init_cash, fees, slippage)
    return {
        "signal": cell.code,
        "min_unlock_pct": cell.min_unlock_pct,
        "cohort": cell.cohort_name,
        "n_trades": portfolio_stats.n_trades,
        "win_rate": portfolio_stats.win_rate,
        "sharpe": portfolio_stats.sharpe,
        "sortino": portfolio_stats.sortino,
        "max_dd": portfolio_stats.max_dd,
        "total_return": portfolio_stats.total_return,
        "mean_pnl": portfolio_stats.mean_pnl,
        "median_pnl": portfolio_stats.median_pnl,
    }
```

### Backtest implementation strategy

Simplest: use vectorbt `Portfolio.from_signals(close, entries, exits, direction='shortonly'|'longonly', fees, slippage, init_cash)` per-token, then concatenate trade ledgers from `pf.trades.records_readable` for aggregate stats. This is what existing v1 backtest does — mirror it. If vectorbt's per-token approach is awkward, fall back to a single multi-asset call.

### Cliff vs linear sub-sweep

After main grid, take the best `(signal, min_pct, cohort)` cell by Sharpe (eligible n_trades≥30). For that cell, re-run with three additional cohort filters:
- `cliff` — vesting_type == "cliff"
- `step` — vesting_type == "step"
- `linear` — vesting_type == "linear"

Output 3 extra rows in the parquet tagged `cohort="vesting:cliff"`, etc.

## Workflow (strict TDD)

Expected commit sequence (~12-14):

1. `test(signals): unlock_grid registry and cohorts`
2. `feat(signals): unlock_grid registry, cohort filters, cell iterator`
3. `test(scripts): sweep_unlock_grid_v15 cell aggregation`
4. `feat(scripts): sweep_unlock_grid_v15 per-cell runner`
5. `test(scripts): sweep_unlock_grid_v15 CLI smoke`
6. `feat(scripts): sweep_unlock_grid_v15 CLI`
7. `test(scripts): sweep_unlock_grid_v15 cliff vs linear sub-sweep`
8. `feat(scripts): sweep_unlock_grid_v15 vesting_type sub-sweep`
9. (real-data) `chore(data): refresh unlock grid sweep parquet + report`

If backtest engine needs a `direction` parameter:
- prepend `test(infra): backtest engine supports long and short direction`
- followed by `feat(infra): backtest engine direction parameter`

After each commit:
- `uv run pytest -q` ≥ previous count
- `uv run ruff check src tests scripts data` clean

Target: 265 → ~280+ tests.

## Acceptance

- Main grid produces 5×4×3 = 60 rows in `data/parquet/unlock_grid_v15.parquet`
- Sub-sweep adds 3 more rows tagged by vesting type
- `reports/phase1_5_grid_sweep.md` exists with top-5 by Sharpe, eligible-by-n_trades, per-cohort breakdown
- pytest ≥ 280
- ruff clean
- ~10-14 small commits, no monolithic commit
- Reports / data committed via `git add -f reports/*.md data/parquet/unlock_grid_v15.parquet`

## Out-of-scope guardrails

Do NOT:
- Run walk-forward (Slice 4)
- Compute multi-signal portfolio weights (Slice 4)
- Touch `docs/research/` (Slice 5)
- Modify Slice 1/2 finalized code (`_unlock_common.py`, signal modules, storage)

## Real-data run

After all code commits:

```bash
uv run python scripts/sweep_unlock_grid_v15.py
```

Expected runtime: 5-15 min. Capture the printed top-5 table in your Execution Report.

Then `git add -f reports/phase1_5_grid_sweep.md data/parquet/unlock_grid_v15.parquet` + final `chore(data)` commit.

## Completion (Execution Report)

```
## Execution Report — Slice 3

### Files touched
- {file}: {what}
...

### Commits (in order)
- {sha} {subject}
...

### Pytest / Ruff
- baseline: 265
- final: {N}
- ruff: clean

### Sweep results
- Cells run: 60 (main) + 3 (vesting sub-sweep) = 63
- Top-5 by Sharpe (eligible: n_trades ≥ 30):
  | rank | signal | min_pct | cohort | sharpe | n_trades | win_rate | max_dd | total_return |
  | --- | --- | --- | --- | --- | --- | --- | --- | --- |
  | 1 | ... |
  ...
- Best vesting_type for that cell: cliff/step/linear with Sharpe={X}
```

Then EXIT. Do NOT archive. Do NOT push.
