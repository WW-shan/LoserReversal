ROLE_FILE: /Users/ww/.claude/.ccg/prompts/codex/builder.md

# Phase 1.5 Slice 4 — Fix R1 (Walk-Forward Parameter Recalibration)

## CRITICAL: Anti-monitor directive

- Do NOT tail/ps/grep for other codex processes. Start writing code IMMEDIATELY.
- Other codex processes belong to the user; UNRELATED to this task.
- Do NOT archive this task. Claude will archive after final LGTM.

## Working directory
`/Users/ww/Project/crypto-alpha-portfolio`

`uv run`, Python 3.11+, 100-char lines, UTC tz-aware, no emojis.

## Context

Slice 4 walk-forward ran with 3 splits × 90-day test → total OOS window = Jul 2023 → Apr 2024 = 9 months, using only **27%** of the 3.4-year data span. The 2024-04 → 2026-05 window (74% of data, 246 of 402 ok-events) was never tested.

This made the verdict effectively meaningless:
- Best OOS Sharpe = 0.57 (v5) with **only 8 trades**
- v5 IS Sharpe was ~0 but OOS jumped to 0.57 — that's selection bias from 3-trade-per-split test windows
- Per Phase 1.5 Pass Criteria: n_trades < 30 → RED, but we can't trust an n=8 verdict

**Critical reframe**: This is NOT a strategy verdict yet — it's a sample-size insufficiency. Re-run with parameters that actually traverse the data.

## Findings to fix

### IMPORTANT #1 — Default walk-forward params don't traverse the data

`run_unlock_walkforward_v15.py` defaults are `n_splits=3, min_train_days=180, test_days=90`. With data starting 2023-01-07 and ending 2026-05-23 (1232 days), this only uses 180 + 3×90 = 450 days = 15 months — wasting 64% of the data.

**Fix**:
- Increase defaults to `n_splits=5, min_train_days=270, test_days=180`. This consumes 270 + 5×180 = 1170 days = ~3.2 years (covers the full span).
- Add a startup log line: `"walk-forward span: train_days={min_train_days} + n_splits×test_days = {total} days; data span = {span} days; coverage = {pct}%"`.
- If coverage < 80%, log a WARNING with recommended params.

### IMPORTANT #2 — Train threshold `min_n_trades=15` too high

Most train folds have only 1-5 trades per signal (per the per-split parquet rows). The current fallback chain (15 → positive-trades → max-sharpe-any) means selection is dominated by the fallback, which is roulette.

**Fix**:
- Lower `min_n_trades=15` → `min_n_trades=5` for train-fold selection.
- Keep the positive-trade fallback as second-tier.
- Drop the "max-sharpe zero-trade" last-resort tier — it produces meaningless selections. If no train fold has ≥1 trade, RETURN None and skip the split (record `selected_cohort='no_train_signal'` in parquet for transparency).

### IMPORTANT #3 — Per-cell event counts shouldn't bottleneck

Even with 270-day train windows, single-cohort+pct cells may have only handful of events. The train-side selection should:
- Aggregate Sharpe across (min_pct, cohort) options first
- Pick top by stats — but the "stats" can be a hybrid: per-cohort+pct backtest as today, OR use a Bayesian-shrunk estimate that pulls low-n-trades cells toward the all-cohort mean

**Fix** (smaller — keep current logic, just lower threshold to 5):
- Apply same pre-selection but use `min_n_trades=5` (changed in #2).
- Note in the methodology section that this is a statistical compromise.

### IMPORTANT #4 — Update Pass/Kill verdict accounting

The walk-forward output is what Slice 5 will read. Ensure clear "n_trades insufficient" vs "Sharpe insufficient" distinction.

**Fix**:
- In the report, add a "Verdict-Ready Summary" section with explicit rows:
  - "Best signal by OOS Sharpe: {name}, sharpe={X}, n_trades={N}"
  - "If n_trades ≥ 50 AND sharpe ≥ 1.0 → GREEN"
  - "If n_trades ≥ 30 AND sharpe ∈ [0.3, 1.0) → YELLOW"
  - "Else → RED"
  - Print the actual classification.

### MINOR #1 — Mean stats vs aggregated stats

Reviewer-level concern: the `aggregate_row` reports `sharpe=mean(per_split_sharpe)` and `win_rate=mean(per_split_win_rate)`. This is technically the mean of ratios, not the ratio of sums. Statistically the ratio of sums is more correct for combining splits.

**Fix**:
- For the aggregate row:
  - `sharpe` = mean of per-split Sharpe (keep — current behavior, common practice)
  - `win_rate` = `total_wins / total_trades` instead of mean(per_split_win_rate)
  - `n_trades` = sum (already correct)
  - `max_dd` = MIN (worst) instead of mean
- Document this in the methodology.

## Workflow (strict TDD)

Expected commits (~8):

1. `test(signals): walkforward aggregate uses total_wins over total_trades`
2. `feat(signals): walkforward aggregate ratio of sums`
3. `test(signals): walkforward selection threshold lowered to 5`
4. `feat(signals): walkforward selection threshold 5 and skip-no-trade splits`
5. `test(scripts): walkforward v15 default params traverse data`
6. `feat(scripts): walkforward v15 defaults n_splits=5 train=270 test=180`
7. `test(scripts): walkforward v15 verdict summary section`
8. `feat(scripts): walkforward v15 emits verdict-ready summary`
9. (real-data) `chore(data): refresh phase1.5 walkforward with calibrated params`

After each commit:
- `uv run pytest -q` ≥ previous count
- `uv run ruff check src tests scripts data` clean

Target: 293 → ~300 tests.

## Acceptance

- New defaults: `n_splits=5, min_train_days=270, test_days=180`
- `min_n_trades=5` for selection
- Splits skip cleanly when no train signal qualifies (no fake selection)
- Verdict-ready summary in report (GREEN/YELLOW/RED classification printed)
- Re-run walk-forward on real data → expect at least one signal with n_trades ≥ 30 in OOS aggregate
- pytest ≥ 300, ruff clean

## Out-of-scope guardrails

Do NOT:
- Modify Slice 1/2/3 frozen code
- Add new signal modules
- Update ROADMAP.md (Slice 5)

## Real-data refresh

After all code commits:
```bash
uv run python scripts/run_unlock_walkforward_v15.py
```

Then `git add -f data/parquet/phase1_5_walkforward.parquet reports/phase1_5_walkforward.md`.

## Completion

```
## Execution Report — Slice 4 Fix R1

### Findings addressed
- [x] Important #1 default params traverse data
- [x] Important #2 selection threshold lowered
- [x] Important #3 lowered threshold (closed via #2)
- [x] Important #4 verdict summary section
- [x] Minor #1 aggregate ratio of sums

### Commits
- ...

### Pytest / Ruff
- baseline: 293
- final: {N}
- ruff: clean

### Refreshed walk-forward results
| signal | mean OOS Sharpe | total n_trades | win_rate | classification |
...

### Best-signal classification
- {name}: Sharpe={X}, n_trades={N} → {GREEN|YELLOW|RED}
```

EXIT. Do NOT archive. Do NOT push.
