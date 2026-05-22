ROLE_FILE: /Users/ww/.claude/.ccg/prompts/codex/builder.md

# Phase 1 Slice 2 — Fix Review Findings (Round 1)

## CRITICAL: Anti-monitor directive
- Do NOT tail/ps/grep for other codex processes.
- Start fixing IMMEDIATELY.

## Working directory
`/Users/ww/Project/crypto-alpha-portfolio`

Use `uv run` for validation.

## Background

Claude + Codex reviewer (parallel) both rated Slice 2 NEEDS_FIX. 1 Critical + 7 Warnings to address. Combined funnel diagnostic from Codex review (you can reuse this verbatim in the report):

```
126 events → 83 has_hl_perp → 18 min_pct>=0.02 → 14 candle fetch ok → 5 entry date in candle range → 3 non-overlapping trades
```

This data sparsity is reality, not a bug — but the scripts must surface it explicitly so Slice 3 / Pass-Kill decision is not misled by Sharpe values built on 1-2 trades.

## Fixes (in this order, separate commits per group)

### Group 1 — Diagnostic + Pass/Kill gating (Critical #1 + Warning #2)

**File**: `scripts/run_unlock_backtest.py`

1. Build a funnel counter object during `run_unlock_backtest()` that tracks:
   - `total_events`: input row count
   - `has_hl_perp_events`: after `has_hl_perp` filter
   - `pct_threshold_events`: after `min_unlock_pct` filter
   - `candle_ok_events`: events for tokens that successfully loaded candles
   - `in_range_events`: events where `(unlock_date - pre_window_days)` AND `unlock_date` both fall inside that token's `prices.index`
   - `non_overlap_events`: events that actually fire (i.e. sum of `entries` across signal dict)
2. Expose `funnel` in the returned dict from `run_unlock_backtest`.
3. Add a "## Event Funnel" section to the markdown report, with `step | events | filter`.
4. Add a "## Decision Gate Check" section at the **TOP** of the report (after `## Config`), with:
   - `n_trades >= 30` → PASS/FAIL bold
   - `Sharpe >= 1.0` → PASS/FAIL
   - `MaxDD >= -25%` → PASS/FAIL
   - **If `n_trades < 30`, prepend the entire report body with a warning header:**
     `> ⚠️ INSUFFICIENT SAMPLE: only N trades. Sharpe is NOT decision-quality. Do not use this report for Pass/Kill.`
   - Use a clear ASCII marker (`!! INSUFFICIENT SAMPLE !!` or `[WARN] INSUFFICIENT SAMPLE`) instead of an emoji — repo style is ASCII-only in scripts.

**File**: `scripts/sweep_unlock_params.py`

5. After computing each grid row, add a boolean `eligible` field = `n_trades >= 30`.
6. Sort rows by `(eligible, sharpe)` desc — eligible rows first, then by Sharpe. So ineligible 1-2 trade Sharpe=100 cannot win.
7. Sweep markdown:
   - Add `eligible` column to the table.
   - Add a "## Eligible-only Ranking" section above the full table, listing only eligible rows (which may be empty — say so).
   - Add a "## Decision Gate Summary" at TOP: how many of the 20 combos are eligible, best-eligible Sharpe.

### Group 2 — Aggregation correctness (Warning #3)

**File**: `scripts/run_unlock_backtest.py:200-205` (`_summed_equity`)

8. Change the aggregation to: reindex each token's equity onto the union date index, **forward-fill only** (do NOT backfill leading NaNs). Leading NaNs mean the token has no active position yet — fill with `init_cash` (per-token starting cash) so that the summed portfolio reflects holding cash for not-yet-started tokens, not fabricated future equity.
9. Document the model in the docstring: "Per-token equity reindexed to union date range, leading gaps filled with init_cash (holding cash), trailing gaps ffilled (position held)."

### Group 3 — Frequency consistency (Warning #5)

10. Remove the `BACKTEST_FREQ = "1D"` module constant.
11. Derive the pandas-friendly freq from `config.interval` via a small helper (e.g. `"1d"`→`"1D"`, `"4h"`→`"4h"`, `"1h"`→`"1h"`). One mapping function placed in `scripts/run_unlock_backtest.py` is fine; do NOT touch `src/infra/`.
12. Pass that freq to `BacktestConfig(freq=...)` and to `_periods_per_year(freq)`.
13. Both scripts must agree on this mapping. `sweep_unlock_params.py` already uses `UnlockBacktestConfig` so it inherits automatically.

### Group 4 — Private import hygiene (Warning #4)

14. **Promote** these helpers to public (drop the leading underscore) in `src/`:
    - `infra.backtest.engine._periods_per_year` → `periods_per_year`
    - `infra.pipeline._candles_cover_range` → `candles_cover_range`
    - `infra.pipeline._interval_timedelta` → `interval_timedelta`
15. Update all callers (search repo). Add deprecation? — no, just rename, repo is private/internal.
16. Update both scripts to import the public names.

### Group 5 — Tighten exception handling (Warning #6)

17. `scripts/run_unlock_backtest.py:68`: replace `except Exception as error` with `except (FileNotFoundError, OSError, duckdb.Error, ValueError, ConnectionError) as error`. Do NOT swallow `KeyError` / `AttributeError` / `TypeError` — those are code bugs.

### Group 6 — Cache failed-token decisions in sweep (Warning #7)

18. `scripts/sweep_unlock_params.py`: maintain a module-level (or function-level) `_failed_tokens: set[str]` cache populated when a token raises in fetch. Before each grid row, pass this set to `run_unlock_backtest` (add an optional `skip_tokens: set[str] | None = None` param to `UnlockBacktestConfig` / `run_unlock_backtest`). Token skipped via cache: log once at sweep start, not once per grid row.

### Group 7 — Fix report text accuracy (Warning #8)

19. Update the `portfolio_model` line in the run_unlock_backtest report to: "Per-token init_cash held in cash until first signal; leading gaps = init_cash (cash held); trailing gaps = last equity (position held); portfolio = sum across all attempted tokens." — match the new aggregation behavior from fix #8.

## Workflow

7 commits expected (one per Group):

1. `fix(scripts): funnel diagnostic + decision gate check`
2. `fix(scripts): sweep eligibility gating by min_trades`
3. `fix(scripts): leading-cash aggregation (no backfill into future)`
4. `fix(scripts): derive backtest freq from interval`
5. `refactor(infra): promote periods_per_year / candles_cover_range / interval_timedelta to public`
6. `fix(scripts): tighten candle-fetch exception scope`
7. `fix(scripts): cache failed tokens across sweep grid + accurate report text`

(Order matters — Group 5 rename touches infra so commits 5 sits in middle; everything else depends on it being done before commit 6/7. Group commits to keep diff readable.)

## Acceptance

- `uv run python scripts/run_unlock_backtest.py --report /tmp/unlock_e2e_v2.md` exits 0
  - Report TOP shows decision gate warning (since n_trades=3 < 30)
  - Funnel section present with all 6 stages
  - Aggregation reflects 12 tokens (not 3) — leading equity should be `12 × init_cash` if NO token has signal at the start date
- `uv run python scripts/sweep_unlock_params.py --report /tmp/unlock_sweep_v2.md` exits 0
  - Top of sweep report says "X of 20 eligible" (probably 0)
  - Eligibility column present
- `uv run pytest -q` still passes (101+ tests)
- `uv run ruff check src tests scripts` clean
- No tests modified (this is scripts-only fix); existing infra tests must pass after the rename refactor (Group 5)

## Out of scope

- Info items (Unicode arrow, duplicate _fmt_pct helpers) — skip
- Walk-forward / Slice 3 work
- New tests (this is integration validation via real run)

## Completion

Execution Report with files changed, commit SHAs (7 expected), final pytest output (last 3 lines), final ruff output, 5-line excerpts from both fresh reports (showing Decision Gate Check + Funnel section + Eligibility column).

Then EXIT.
