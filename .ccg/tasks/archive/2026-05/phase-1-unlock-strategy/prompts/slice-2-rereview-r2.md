ROLE_FILE: /Users/ww/.claude/.ccg/prompts/codex/reviewer.md

# Phase 1 Slice 2 — Re-review After Round 2 Fix

## CRITICAL: Read-only

NO write permission.

## Working directory
`/Users/ww/Project/crypto-alpha-portfolio`

## Context

Round 1 fix scored 89/100 NEEDS_ANOTHER_FIX with 1 Critical + 2 Warnings on capital accounting. Round 2 added:
- `b81913e` fix(scripts): report candidate vs backtested token counts separately
- `e89cf26` refactor(scripts): scope sweep failed_tokens cache to run_sweep

## Your job

Verify each Round 1 leftover issue is actually resolved. Check for any NEW issues.

Use `git show b81913e e89cf26` and inspect current files. Read fresh report `/tmp/unlock_e2e_v3.md` or `reports/unlock_v1_backtest.md`.

## Round 1 leftover issues (re-verify each)

### Critical (from Round 1 new-issues)
1. **n_tokens vs equity start mismatch** — verify:
   - Config table now shows `n_candidate_tokens`, `n_backtested_tokens`, `n_failed_tokens` separately (not just `n_tokens`)
   - Equity start equals `n_backtested_tokens × init_cash`
   - Failed tokens list rendered when present (LISTA should appear)

### Warnings
2. **`portfolio_model` text accuracy** — verify the new wording matches actual behavior. Specifically the phrase "portfolio = sum across backtested tokens" and "Failed-fetch tokens are NOT included in the portfolio capital base" must be present.
3. **`_failed_tokens` module-global → local** — verify:
   - `_failed_tokens: set[str] = set()` at module top is REMOVED from `scripts/sweep_unlock_params.py`
   - A local `failed_tokens` variable inside `run_sweep()` replaces it
   - Seeded from `config.skip_tokens`
   - All references updated consistently

## Aggregation sanity check (numerical)

Read `/tmp/unlock_e2e_v3.md`:
- `n_candidate_tokens` = ?
- `n_backtested_tokens` = ?
- `n_failed_tokens` = ?
- First equity row in Equity Curve = ?
- Expected: first equity == n_backtested × init_cash

Confirm or report mismatch.

## Check for NEW issues introduced by Round 2

- Any test broken by the rename `n_tokens` → `n_candidate_tokens` / `n_backtested_tokens`?
- Any caller of `run_unlock_backtest()` (besides `sweep_unlock_params.py`) that still expects the old `n_tokens` key in the dict?
- Did the failed_tokens variable scoping break the cross-grid-row carry-over? (It should still propagate within ONE `run_sweep` call, just not across calls.)

## Output format

```
## Slice 2 Round 2 Re-Review

### Verdict
[LGTM / STILL NEEDS_FIX / NEW ISSUES]

### Per-item status
1. Critical (capital accounting): [FIXED / NOT FIXED / partial — detail]
2. Warning (portfolio_model wording): [FIXED / NOT FIXED]
3. Warning (failed_tokens scoping): [FIXED / NOT FIXED]

### Aggregation sanity check
- n_candidate: __
- n_backtested: __
- n_failed: __
- first equity: __
- expected (n_backtested × init_cash): __
- match: yes/no

### New issues introduced (count: N)
- ...

### Scoring
- Critical resolution: XX/30
- Spec coverage: XX/20
- Correctness: XX/20
- Code quality: XX/15
- Style consistency: XX/15

TOTAL: XX/100

RECOMMENDATION: [LGTM (proceed to Slice 3) / NEEDS_ANOTHER_FIX / BLOCK]
```

If LGTM and TOTAL ≥ 90, Slice 2 is locked in.

Read-only. Do not modify files.
