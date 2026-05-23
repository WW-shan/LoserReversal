ROLE_FILE: /Users/ww/.claude/.ccg/prompts/codex/builder.md

# Phase 1.5 Slice 3 — Fix R1

## CRITICAL: Anti-monitor directive

- Do NOT tail/ps/grep for other codex processes. Start writing code IMMEDIATELY.
- Other codex processes belong to the user; UNRELATED to this task.
- Do NOT archive this task. Claude will archive after final LGTM.

## Working directory
`/Users/ww/Project/crypto-alpha-portfolio`

`uv run`, Python 3.11+, 100-char lines, UTC tz-aware, no emojis.

## Context

Reviewer flagged 3 Important + 2 Minor. Fix in one TDD round. No Critical issues — backtest correctness is sound (Sharpe 1.60 holds, no leak).

## Findings

### IMPORTANT #1 — Vesting sub-sweep hidden in report

`reports/phase1_5_grid_sweep.md` shows `best_sharpe = n/a` for vesting rows because `_cohort_breakdown_rows` filters by `eligible` (n_trades ≥ 30) and the 3 vesting rows happen to have n_trades < 30 each (21 / 29 / 0). The parquet itself has the correct Sharpe (cliff=1.65, step=1.08, linear=0.0), but the report hides it.

**Fix**:
- In `scripts/sweep_unlock_grid_v15.py`, add a dedicated `## Vesting Sub-Sweep` section to the report BEFORE the "Per-Cohort Breakdown" section.
- Table columns: `vesting_type | n_trades | win_rate | sharpe | max_dd | total_return`
- Use raw values regardless of eligibility (since the sub-sweep deliberately runs the SAME best cell, eligibility was already established by the parent cell).
- Add a footnote: "Sub-sweep inherits config from the best main-grid cell ({signal} / {min_pct} / {cohort}). Eligibility threshold (n_trades ≥ 30) is informational only here."

**Tests**:
- Add `test_render_report_includes_vesting_subsection` in `tests/scripts/test_sweep_unlock_grid_v15.py` — assert the rendered markdown contains `## Vesting Sub-Sweep` and the three vesting types listed.

### IMPORTANT #2 — Active-capital aggregation not documented

`backtest_signals` aggregates only tokens that emitted ≥ 1 signal. Total-return and max_dd therefore depend on how many tokens pass each cell (active-capital portfolio rather than fixed-universe). The reviewer correctly notes this differs from `scripts/run_unlock_backtest.py` which keeps flat-cash bookkeeping for inactive tokens.

**Fix** (Option A — documentation, simpler):
- Add a `Methodology` section at the TOP of `reports/phase1_5_grid_sweep.md` explaining:
  - Each token's signal is backtested independently with $init_cash starting capital
  - Portfolio equity is the sum of per-token equities at each timestamp
  - Inactive tokens contribute zero (no flat-cash padding)
  - Total return is relative to summed initial capital, NOT to a single $10k account
  - This is an "active-capital" view; live deployment requires position sizing
- Also add a `methodology` string to the parquet metadata via `pq.write_table(..., metadata={...})` OR a sidecar JSON `unlock_grid_v15.meta.json` capturing this same text + the cell budget per token.

**Tests**:
- `test_report_includes_methodology_section`
- `test_parquet_has_methodology_metadata` (if you use parquet metadata) OR `test_meta_json_alongside_parquet` (if sidecar)

### IMPORTANT #3 — `--date-start/--date-end` only filter events, not measurement window

`--date-start` and `--date-end` are applied to events but the price index used for Sharpe / drawdown is the full token candle history (2023-now). If a user passes `--date-start 2025-01-01`, the metrics still include flat-cash 2023-2024.

**Fix**:
- In `sweep_unlock_grid_v15.py`, after applying date filter to events, also clip each token's price series to `[date_start, date_end]` before passing to backtest.
- If `date_start`/`date_end` are None, behavior is unchanged (back-compat).
- Add a test that verifies passing `--date-start 2025-01-01` truncates equity series accordingly.

**Tests**:
- `test_date_range_clips_price_window_not_just_events`

### MINOR #1 — `cohort` column overloaded

The parquet uses `cohort` for both category cohorts and `vesting:*` rows. Reviewer recommends a `sweep_kind` column.

**Fix**:
- Add `sweep_kind: string` column to the parquet. Values: `"category"` for main grid, `"vesting"` for sub-sweep.
- Keep `cohort` column as-is (don't migrate the schema in a breaking way for Slice 4).
- Re-run the sweep to regenerate parquet with new column.

**Tests**:
- `test_parquet_has_sweep_kind_column`

### MINOR #2 — pytest not run by reviewer

Just informational. Make sure `uv run pytest -q` is part of your validation loop after each commit.

## Workflow (strict TDD)

Expected commits (~7-9):

1. `test(scripts): vesting sub-sweep section rendered in grid report`
2. `feat(scripts): render vesting sub-sweep table in grid report`
3. `test(scripts): grid report includes methodology section`
4. `feat(scripts): document active-capital methodology in report`
5. `test(scripts): date range clips price window for grid sweep`
6. `feat(scripts): clip price series to date range in grid sweep`
7. `test(scripts): grid parquet has sweep_kind column`
8. `feat(scripts): tag main vs vesting rows with sweep_kind`
9. (real-data) `chore(data): refresh grid sweep parquet and report with sub-sweep and methodology`

After each commit:
- `uv run pytest -q` ≥ previous count (280 → ~285 target)
- `uv run ruff check src tests scripts data` clean

## Acceptance

- Report contains `## Vesting Sub-Sweep` with raw Sharpe/n_trades for cliff/step/linear
- Report contains `## Methodology` explaining active-capital aggregation
- `--date-start`/`--date-end` clip both events AND price index
- Parquet has new `sweep_kind` column
- All 3 Important + 1 Minor (cohort schema) addressed
- pytest ≥ 285
- ruff clean
- Real-data parquet + report refreshed

## Out-of-scope guardrails

Do NOT:
- Walk-forward (Slice 4)
- New signal modules
- Modify Slice 1/2 finalized code

## Completion

```
## Execution Report — Slice 3 Fix R1

### Findings addressed
- [x] Important #1 vesting sub-sweep visibility
- [x] Important #2 active-capital methodology
- [x] Important #3 date-range price clipping
- [x] Minor #1 sweep_kind column

### Commits
- {sha} {subject}
...

### Pytest / Ruff
- baseline: 280
- final: {N}
- ruff: clean

### Refreshed data confirmation
- parquet shape: 63 rows × N cols
- new sweep_kind column: {category=60, vesting=3}
- report includes Vesting Sub-Sweep with Sharpe values: cliff={X}, step={Y}, linear={Z}
- report includes Methodology section
```

EXIT. Do NOT archive. Do NOT push.
