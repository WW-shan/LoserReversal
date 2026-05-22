ROLE_FILE: /Users/ww/.claude/.ccg/prompts/codex/builder.md

# Phase 1 Slice 3 — Walk-Forward Validation + Pass/Kill Verdict

## CRITICAL: Anti-monitor directive
- Do NOT tail/ps/grep. Start coding IMMEDIATELY.

## Working directory
`/Users/ww/Project/crypto-alpha-portfolio`

Use `uv run` for execution.

## Goal

Run walk-forward validation on the unlock-short strategy and emit a Pass/Kill verdict against `task.json.passCriteria`.

Data context (from Slice 2 sweep):
- 83 `has_hl_perp` events spanning 2025-06-01 → 2026-05-15 (348 days)
- 7 backtested HL tokens, 1 failed (LISTA)
- Slice 2 default config gives only 3 trades total (3 in-range non-overlapping events). Low min_pct (0.01) gives 18-24 trades but **negative Sharpe**, hinting strategy is NOT robust.
- **Expected outcome: RED (Kill).** But the verdict must come from walk-forward OOS evidence, not assumption.

## Scope (DO NOT exceed)

Create:
- `scripts/run_unlock_walkforward.py` — walk-forward CLI

Modify (only if necessary to support date-range filtering):
- `scripts/run_unlock_backtest.py` — add `date_start` / `date_end` fields to `UnlockBacktestConfig`, filter `events` accordingly inside `run_unlock_backtest`
- `scripts/sweep_unlock_params.py` — pass `date_start` / `date_end` through `replace()` so each grid row honors the window

## Architectural decisions (use these, do NOT redesign)

### Date-range support (Modification)

`UnlockBacktestConfig` adds:
```python
date_start: datetime | None = None  # filter events: unlock_date >= date_start
date_end: datetime | None = None    # filter events: unlock_date <= date_end
```

Inside `run_unlock_backtest`, after the existing filters, also apply:
```python
if config.date_start is not None:
    events = events[events["unlock_date"] >= config.date_start]
if config.date_end is not None:
    events = events[events["unlock_date"] <= config.date_end]
```

This means candles are still fetched for the full data range (cheaper), but only events within the window generate signals → ensures clean IS/OOS separation.

Add `date_start_events` / `date_end_events` fields to the funnel for clarity.

### Walk-forward script (`run_unlock_walkforward.py`)

1. Load unlocks parquet via `infra.storage.read_unlocks()`, filter `has_hl_perp=True`, get date span `[start, end]`.
2. Use `infra.backtest.walkforward.walk_forward_splits` with these defaults (CLI configurable):
   - `n_splits=3`
   - `mode="expanding"`
   - `min_train_days=150`
   - `test_days=60`
   - If `walk_forward_splits` raises ValueError (span too short), retry with smaller `min_train_days` automatically (down to 90) and log it. If still infeasible → exit 1 with clear message.
3. For each split `((train_start, train_end), (test_start, test_end))`:
   a. **IS phase**: run `sweep_unlock_params.run_sweep` on the IS window only (set `date_start=train_start, date_end=train_end` on the config). Collect 20 rows.
   b. **IS selection**: pick the best config for OOS evaluation:
      - Prefer eligible rows (`n_trades >= 30`). If any eligible: pick max Sharpe among eligible.
      - **Fallback**: no eligible rows (likely given data sparsity) → pick max Sharpe overall, but mark with `eligible_in_is=False` flag.
      - Record `is_best_config`, `is_sharpe`, `is_n_trades`.
   c. **OOS phase**: run `run_unlock_backtest` on OOS window only (`date_start=test_start, date_end=test_end`) with `is_best_config`. Capture OOS Sharpe, OOS MaxDD, OOS n_trades.
4. Aggregate across N splits:
   - `oos_sharpe_mean` (simple mean)
   - `oos_sharpe_min` (worst split — used for robustness check)
   - `oos_max_dd_worst` (most negative across splits)
   - `oos_n_trades_total` (sum)
   - `is_oos_decay = (mean_is_sharpe - mean_oos_sharpe) / mean_is_sharpe` (positive = OOS worse than IS, expected)
5. Verdict logic (matches `task.json.passCriteria` + ROADMAP):

```
GREEN: oos_sharpe_mean >= 0.7 AND oos_n_trades_total >= 30 AND oos_max_dd_worst >= -0.25
YELLOW: 0.3 <= oos_sharpe_mean < 0.7 AND oos_n_trades_total >= 15 AND oos_max_dd_worst >= -0.30
RED: everything else (including insufficient sample)
```

Use these EXACT thresholds. If a flag triggers "insufficient sample" (e.g. total OOS trades < 15), the verdict is RED with reason `"insufficient_sample"`.

### CLI flags

- `--n-splits INT` (default 3)
- `--mode STR` (default "expanding", choices `["expanding", "rolling"]`)
- `--min-train-days INT` (default 150)
- `--test-days INT` (default 60)
- `--interval STR` (default "1d")
- `--init-cash FLOAT` (default 10000)
- `--fees FLOAT` (default 0.0005)
- `--slippage FLOAT` (default 0.0002)
- `--report PATH` (default `reports/unlock_v1_walkforward.md`)
- (no separate `--out-config PATH` — verdict is in the report only)

### Report (`reports/unlock_v1_walkforward.md`)

Structure (markdown):

```
# Unlock Short V1 — Walk-Forward Validation

_Generated <UTC>_

## Verdict: [GREEN / YELLOW / RED]
Reason: <short string explaining trigger>

## Data Span
- start: 2025-06-01
- end: 2026-05-15
- total span: 348 days
- n_candidate_events (has_hl_perp): 83

## Walk-Forward Config
- n_splits: 3
- mode: expanding
- min_train_days: 150
- test_days: 60

## Per-Split Results

| split | is_start | is_end | oos_start | oos_end | is_best_config | is_sharpe | is_n_trades | oos_sharpe | oos_n_trades | oos_max_dd | eligible_in_is |
| ---: | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | :---: |
| 1 | 2025-06-01 | 2025-11-01 | 2025-11-01 | 2025-12-31 | pre=10 min=0.02 | 1.91 | 2 | n/a | 0 | n/a | no |
| ...

## Aggregate OOS Stats

| Metric | Value | Threshold | Status |
| --- | --- | --- | --- |
| OOS Sharpe (mean) | 0.42 | >= 0.7 (GREEN) / >= 0.3 (YELLOW) | YELLOW |
| OOS Sharpe (min/worst) | -0.50 | >= 0 desired | FAIL |
| OOS n_trades (total) | 12 | >= 30 (GREEN) / >= 15 (YELLOW) | FAIL |
| OOS Max DD (worst) | -18% | >= -25% (GREEN) / >= -30% (YELLOW) | PASS |
| IS→OOS decay | 78% | <= 30% desired | FAIL |

## Decision

[Single paragraph: "verdict is X because Y. Recommended action: Z (archive / include in portfolio with weight A%)."]
```

### Update `ROADMAP.md` after writing report

Update `docs/research/loser-reversal-indicator/ROADMAP.md` Phase 1 section with:
- Verdict line: `**Phase 1 verdict: RED — KILL**` (or GREEN / YELLOW)
- Key numbers: OOS Sharpe mean / n_trades total / worst MaxDD
- Reason in one sentence

Do NOT update other sections of ROADMAP.

## Conventions

- `from __future__ import annotations`
- 100-char lines
- argparse with validation
- UTC tz-aware datetimes
- No emoji in code, commits, or report bodies (use `[WARN]`, `**FAIL**`, etc.)
- Skip tokens with no candle data — already handled by Slice 2 helpers

## Workflow

3-4 commits expected:
1. `feat(scripts): date-range filter in unlock backtest config` (config + run_unlock_backtest + sweep changes)
2. `feat(scripts): unlock walk-forward validation runner` (run_unlock_walkforward.py)
3. `docs(roadmap): Phase 1 verdict from walk-forward run`
4. (optional) `chore(reports): seed walkforward.md from real run`

## Tests

- New `tests/scripts/` is not required — script is integration tested by real run
- BUT: add a quick unit test for the date-range filter logic in `tests/scripts/test_walkforward_runner.py` (or skip if it adds too much scaffolding — judge call)
- Confirm `uv run pytest -q` stays green (101+ tests)

## Acceptance

- `uv run python scripts/run_unlock_walkforward.py --report /tmp/unlock_wf.md` exits 0
- `/tmp/unlock_wf.md` contains the Verdict line at top
- ROADMAP.md Phase 1 section updated with verdict
- `uv run pytest -q` clean
- `uv run ruff check src tests scripts` clean
- Per-split table shows ALL 3 splits with numbers (even if some are n/a due to 0 OOS trades)

## Out of scope

- Live execution
- ML feature engineering
- Multiple signal variants

## Completion

Execution Report with files changed, commits, final pytest output, ruff output, the actual verdict + key numbers (mean OOS Sharpe, total OOS trades, worst MaxDD, decay%), and a 10-line excerpt of the walkforward report showing Verdict + Aggregate OOS Stats section.

Then EXIT.
