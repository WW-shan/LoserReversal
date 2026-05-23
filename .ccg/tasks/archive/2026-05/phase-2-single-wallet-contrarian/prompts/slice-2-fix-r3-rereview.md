ROLE_FILE: /Users/ww/.claude/.ccg/prompts/codex/reviewer.md

# Phase 2 Slice 2 Fix R3 — Final Re-review

## CRITICAL: Read-only

NO write permission.

## Working directory
`/Users/ww/Project/crypto-alpha-portfolio`

## Context

Slice 2 fix R3 added 3 commits for 5 Minor polish items from R2 subagent review:
- `614e2d5 test(scripts): sweep ranking fixture distinguishes IR vs Sharpe`
- `f29536b chore(scripts): docstring + comments for mixed sort keys`
- `6a086b4 chore(scripts): tidy skip summary guard + funnel row formatting`

## Verify

### Minor 1 — Sweep ranking test discriminates IR vs Sharpe

`tests/scripts/test_sweep_wallet_holding.py` — sweep ranking test fixture should now have rows where IR-rank vs Sharpe-rank yields different order (e.g., one row with high Sharpe but low IR, another with low Sharpe but high IR), and the assertion verifies IR-rank wins.

### Minor 2 — Empty-pool no skip summary

`scripts/run_wallet_reverse_backtest.py` — `[skip summary]` print should be guarded by `if wallets:` so empty path is silent. Builder reports stderr is empty on empty-pool run.

### Minor 3 — `_has_non_null_time` docstring

`scripts/run_wallet_reverse_backtest.py:613-619` — function should have a docstring documenting "frame has time column with non-null OR DatetimeIndex with non-null; both missing → False" contract.

### Minor 4 — `_sort_sharpe` vs `_sort_eligible_ir` explanation

`scripts/run_wallet_reverse_backtest.py:132` (or near per-wallet sort) — should have inline comment explaining "per-wallet shown by Sharpe; sweep ranks by IR".

### Minor 5 — Funnel markdown row as single f-string

`scripts/run_wallet_reverse_backtest.py:505-506` and similar — adjacent string literal concatenation should be either single f-string or explicit `+`.

## Check for new issues

- Any test broken by the new fixture values?
- Empty-pool run actually silent (no leftover prints)?
- Docstring/comments don't violate ruff line length?

## Output

```
## Phase 2 Slice 2 Fix R3 Re-Review

### Verdict
[LGTM (ready for Slice 3) / NEEDS_FIX]

### Per-finding Status
1. Minor (sweep test discriminates): [FIXED / NOT FIXED]
2. Minor (empty-pool no summary): [FIXED / NOT FIXED]
3. Minor (_has_non_null_time docstring): [FIXED / NOT FIXED]
4. Minor (mixed sort keys comment): [FIXED / NOT FIXED]
5. Minor (funnel f-string): [FIXED / NOT FIXED]

### New issues introduced (count: N)
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
