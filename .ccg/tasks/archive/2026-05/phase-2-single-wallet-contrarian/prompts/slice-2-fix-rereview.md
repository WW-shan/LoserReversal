ROLE_FILE: /Users/ww/.claude/.ccg/prompts/codex/reviewer.md

# Phase 2 Slice 2 Fix — Re-review

## CRITICAL: Read-only

NO write permission.

## Working directory
`/Users/ww/Project/crypto-alpha-portfolio`

## Context

Slice 2 round 1 scored 71/100 NEEDS_FIX (2 Critical + 3 Warnings). Fix added 7 commits:
- `97d70fb test(scripts): backtest runner trade-level IR cases`
- `53ad14d feat(scripts): add trade-level IR + daily-resampled Sharpe`
- `63c3a98 fix(scripts): update decision gate to use trade-level IR`
- `06bf6ce test(scripts): backtest skip reason buckets`
- `e9b5883 feat(scripts): skip reason buckets in funnel`
- `f9901c4 test(scripts): backtest + sweep runner regression`
- `5524be0 feat(scripts): add sweep trade-level IR column`

## Verify each finding

### Critical
1. **Decision metric mismatch fixed** — verify report now shows:
   - `Trade-level IR | >= 1.2 | -4.83 | FAIL`
   - `Daily Sharpe | >= 1.0 | -21.15 | FAIL`
   - `Hourly Sharpe (informational) | n/a | -27.12 | n/a` (no PASS/FAIL)
   - Decision gate now uses trade-level IR.
2. **Commit granularity fixed** — 7 separate commits per task (test+impl pairs).

### Warnings
3. **Skip reason buckets** — verify funnel shows 5 separate skip reasons (no_fills, no_open_dir, no_retail_size, no_candle, no_valid_pair); sum should equal `n_candidate - n_backtested - n_failed`.
4. **Regression tests** — verify `tests/scripts/test_run_wallet_reverse_backtest.py` and `test_sweep_wallet_holding.py` exist with 3+ cases each.
5. **MaxDD path-dependent** — confirm MaxDD calculation unchanged (still on equity curve, not affected by IR changes).

## Numerical sanity check

- skip_no_fills = 34 means 34/50 wallets had empty fills cache. Confirm this is **really** the read_fills result, not a coding bug (e.g., wrong path lookup).
- Trade-level IR = -4.83: is this a reasonable scale for trade-level IR over ~4 months with 28k trades?
- Single-wallet trade-level IRs: any sanity issues (e.g. all wallets identical IR suggests aggregation bug)?

## Check for new issues introduced by fix

- Test imports / mocking style consistent with existing tests?
- Any leftover hourly-Sharpe gates anywhere in the codebase?
- Skip reason logic actually catches all paths (no orphan return statements)?

## Output

```
## Phase 2 Slice 2 Fix Re-Review

### Verdict
[LGTM (ready for Slice 3) / STILL NEEDS_FIX]

### Per-item Status
1. Critical (metric mismatch): [FIXED / NOT FIXED]
2. Critical (commit granularity): [FIXED / NOT FIXED + commit count]
3. Warning (skip reason buckets): [FIXED / NOT FIXED + bucket count]
4. Warning (regression tests): [FIXED / NOT FIXED + test count]
5. Warning (MaxDD): [UNCHANGED / REGRESSED]

### Numerical evidence
- Trade-level IR: __
- Daily Sharpe: __
- Hourly Sharpe: __
- Skip breakdown total matches n_candidate - n_backtested - n_failed: yes/no

### New issues introduced
- count: N
- ...

### Scoring
- Critical resolution: XX/30
- Spec coverage: XX/20
- Correctness: XX/20
- Test quality: XX/15
- Style consistency: XX/15

TOTAL: XX/100

RECOMMENDATION: [LGTM / NEEDS_FIX]
```

Read-only.
