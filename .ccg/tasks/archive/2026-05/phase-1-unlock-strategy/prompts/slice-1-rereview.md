ROLE_FILE: /Users/ww/.claude/.ccg/prompts/codex/reviewer.md

# Phase 1 Slice 1 — Re-review After Fix

## CRITICAL: Read-only

You have NO write permission. Do NOT modify any file.

## Working directory
`/Users/ww/Project/crypto-alpha-portfolio`

## Context

You previously reviewed Slice 1 (commits `e6827d8` through `82cd9de`) and scored 85/100 NEEDS_FIX, listing 1 Critical + 4 Warnings + 2 Info.

Three fix commits have been added:
- `16323c4` test(slice-1): regression tests for review findings
- `f0374e2` fix(backtest): validate mode and positive ints in walk_forward_splits
- `992612b` fix(signals): validate pre_window_days and coerce UTC index

## Your job

Verify each of the previously-found Critical + Warning items is actually resolved by these fix commits AND a regression test exists that would fail if the fix were reverted.

Use:
- `git show 16323c4 f0374e2 992612b` to inspect each fix
- `git log --oneline -10` for orientation
- `cat src/signals/unlock_v1.py` and `cat src/infra/backtest/walkforward.py` for current state

## Previously-found issues (re-verify each)

### Critical
1. **walk_forward_splits mode validation order** — was: `n_splits<=0` early return masked invalid mode. Verify: `walk_forward_splits(start, end, n_splits=0, mode="invalid")` now raises a ValueError that mentions mode (not n_splits).

### Warnings
2. **pre_window_days not validated** — verify: `pre_window_days <= 0` raises ValueError, with regression test asserting both 0 and -1.
3. **min_train_days / test_days not validated** — verify: each ≤ 0 raises ValueError, with regression tests for each parameter independently.
4. **Price index UTC coercion** — verify: a naive datetime index produces the SAME signal output as the equivalent UTC tz-aware index (no silent skipping). Regression test must use a naive index and compare against the aware version's output.
5. **Trailing blank line at EOF in unlock_v1.py** — verify: file ends with exactly one newline. Run `git diff --check HEAD~3..HEAD` mentally.

### Other checks
- Were any NEW issues introduced by these fix commits? (incomplete validation, wrong error messages, regressions in existing tests)
- Is the validation logic placed at the FUNCTION ENTRY (fail-fast) rather than after work has begun?
- Are error messages descriptive (mention the offending param name)?

## Output format

```
## Slice 1 Re-Review

### Verdict
[LGTM / STILL NEEDS_FIX / NEW ISSUES]

### Per-item status
1. Critical (mode order): [FIXED with regression / NOT FIXED / partial]
2. Warning (pre_window_days): [FIXED with regression / NOT FIXED / partial]
3. Warning (min_train_days / test_days): [FIXED with regression / NOT FIXED / partial]
4. Warning (UTC coercion): [FIXED with regression / NOT FIXED / partial]
5. Warning (EOF newline): [FIXED / NOT FIXED]

### New issues found (count: N)
- [issue 1, file:line, severity]
...

### Scoring
- Spec coverage: XX/20
- Correctness: XX/20
- Code quality: XX/20
- Test quality: XX/20
- Style consistency: XX/20

TOTAL: XX/100

RECOMMENDATION: [LGTM (proceed to Slice 2) / NEEDS_ANOTHER_FIX / BLOCK]
```

If verdict is LGTM and TOTAL ≥ 90, Slice 1 is locked in.

Do NOT modify any file. Review only.
