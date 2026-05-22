ROLE_FILE: /Users/ww/.claude/.ccg/prompts/codex/reviewer.md

# Phase 1 Slice 2 — Re-review After Fix

## CRITICAL: Read-only

NO write permission. Do NOT modify files.

## Working directory
`/Users/ww/Project/crypto-alpha-portfolio`

## Context

Previously reviewed Slice 2 (commits `f28371d`, `8e85f7f`) at 79/100 NEEDS_FIX with 1 Critical + 7 Warnings.

7 fix commits added:
- `39d4dab` fix(scripts): funnel diagnostic + decision gate check
- `bb115b4` fix(scripts): leading-cash aggregation (no backfill into future)
- `9bf96ae` fix(scripts): derive backtest freq from interval
- `831c15a` refactor(infra): promote periods_per_year / candles_cover_range / interval_timedelta to public
- `2e2298d` fix(scripts): tighten candle-fetch exception scope
- `1f1b15f` fix(scripts): sweep eligibility gating by min_trades
- `1b57ce6` fix(scripts): cache failed tokens across sweep grid + accurate report text

## Your job

For each of the previously-found 1 Critical + 7 Warnings, verify the fix is actual code change (not just a comment), and the change resolves the underlying problem. Check for any NEW issues the refactor introduced.

Use `git show <sha>`, `cat scripts/run_unlock_backtest.py`, `cat scripts/sweep_unlock_params.py`, `cat src/infra/backtest/engine.py`, `cat src/infra/pipeline.py` to inspect.

Also read fresh report `cat reports/unlock_v1_backtest.md` (or `/tmp/unlock_e2e_v2.md`) and `reports/unlock_v1_sweep.md` to verify content.

## Previously-found issues (re-verify each)

### Critical
1. **Sweep ranking by Sharpe alone** — verify: sweep now has `eligible` column AND rows are sorted `(eligible, sharpe)` so 1-2 trade artifacts cannot win. Decision Gate Summary shows count of eligible combos.

### Warnings
2. **Funnel diagnostic missing** — verify report contains "## Event Funnel" with all 6 stages (total → has_hl_perp → pct_threshold → candle_ok → in_range → non_overlap).
3. **`.ffill().bfill()` fabricating leading equity** — verify `_summed_equity` (or its successor): leading NaNs filled with `init_cash` (cash held), trailing ffill (position held). NO bfill.
4. **Private import** — verify `periods_per_year` / `candles_cover_range` / `interval_timedelta` are now public (no leading underscore), all callers updated, and no `_periods_per_year` references remain.
5. **`BACKTEST_FREQ = "1D"` hardcoded** — verify it's derived from `config.interval` via a mapping function, and works for at least `"1d"`, `"4h"`, `"1h"`.
6. **`except Exception` too broad** — verify it now catches specific exceptions only (FileNotFoundError, OSError, duckdb.Error, ValueError, ConnectionError). KeyError/AttributeError/TypeError should propagate.
7. **Sweep re-fetches failed tokens 20×** — verify there's a `_failed_tokens` cache (or similar) that prevents re-trying. Logged once at sweep start, not 20 times.
8. **Report `portfolio_model` text inaccurate** — verify updated text matches new behavior (leading=cash, trailing=last equity).

## Output format

```
## Slice 2 Re-Review

### Verdict
[LGTM / STILL NEEDS_FIX / NEW ISSUES]

### Per-item status
1. Critical (sweep eligibility): [FIXED / NOT FIXED / partial — detail]
2-8. Warnings: [FIXED / NOT FIXED / partial — detail]

### New issues introduced by fix (count: N)
- ...

### Aggregation sanity check (numerical)
- After fix #3, portfolio equity should START at `n_tokens × init_cash` if no token has an active position on day 1. Check this against `/tmp/unlock_e2e_v2.md` or `reports/unlock_v1_backtest.md` equity curve.

### Scoring
- Critical resolution: XX/30
- Spec coverage: XX/20
- Correctness: XX/20
- Code quality: XX/15
- Style consistency: XX/15

TOTAL: XX/100

RECOMMENDATION: [LGTM (proceed to Slice 3) / NEEDS_ANOTHER_FIX / BLOCK]
```

Investigate aggregation correctness with actual numbers. If equity start ≠ `n_tokens × init_cash`, dig into why.

Do NOT modify any file. Review only.
