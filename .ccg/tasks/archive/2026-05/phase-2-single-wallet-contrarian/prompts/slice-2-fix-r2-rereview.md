ROLE_FILE: /Users/ww/.claude/.ccg/prompts/codex/reviewer.md

# Phase 2 Slice 2 Fix R2 — Re-review

## CRITICAL: Read-only

NO write permission.

## Working directory
`/Users/ww/Project/crypto-alpha-portfolio`

## Context

Slice 2 fix R2 added 8 commits to address 4 Important + 3 Minor from prior review (Codex 94/100, subagent NEEDS_FIX with detail):

- `0dfcda0 fix(scripts): sweep ranks by trade_level_ir not hourly Sharpe` (Important 1)
- `668660c docs(reports): IR overlap disclaimer in portfolio stats` (Important 2)
- `2235671 test(scripts): skip_reason precise bucket labels` (Important 3 test)
- `d8ff732 fix(scripts): rename skip_no_valid_pair to skip_no_qualifying_event` (Important 3 impl)
- `525c65d test(scripts): pin trade_level_ir numerical correctness` (Important 4)
- `73c39a8 style(scripts): re-indent _empty_coin_result` (Minor 5)
- `378ba32 fix(scripts): remove redundant trade_level_ir length guard` (Minor 6)
- `0b5330a fix(scripts): collapse skip logs to single summary line` (Minor 7)

Use `git show <sha>` and inspect:
- `scripts/sweep_wallet_holding.py`
- `scripts/run_wallet_reverse_backtest.py`
- `tests/scripts/test_run_wallet_reverse_backtest.py`
- `reports/wallet_reverse_v1_backtest.md`
- `reports/wallet_reverse_v1_sweep.md`

## Verify each finding

### Important
1. **Sweep ranks by trade_level_ir** — verify `_sort_eligible_sharpe` renamed to `_sort_eligible_ir`, sweep "Decision Gate Summary" says "Best holding by Trade-level IR", `_best_summary` prints IR + Sharpe + n_trades.
2. **IR overlap disclaimer** — verify italic note above Trade-level IR row in `## Portfolio Stats`: "Trade-level IR aggregates each (entry, exit) pair's gross return as if trades were independent. For overlapping/concurrent positions on the same coin, the realized equity-curve metrics (Daily Sharpe, Hourly Sharpe, Max DD) are authoritative."
3. **skip_no_qualifying_event** — verify `_skip_reason_for_empty_events` renamed bucket, NaN-time/coin now correctly returns `skip_no_qualifying_event`, funnel column updated.
4. **Trade-level IR numerical pin** — verify test asserts `pytest.approx(expected, rel=1e-3)` against a hand-computed value.

### Minor
5. **`_empty_coin_result` indent uniform** — verify dict literal indents consistently.
6. **Trade-level IR redundant guard removed** — verify `len(returns) < 2` early return removed OR documented.
7. **Skip log collapsed to summary** — verify single `[skip summary] no_fills=N ...` line at end of loop instead of per-wallet stderr.

## Check for NEW issues

- Renaming `skip_no_valid_pair` → `skip_no_qualifying_event`: any test/reference left using the old name?
- Sweep rank change: does ranking actually shift compared to previous Sharpe-based output?
- Test pin: is the hand-computed expected value documented in a comment?

## Output format

```
## Phase 2 Slice 2 Fix R2 Re-Review

### Verdict
[LGTM (ready for Slice 3) / STILL NEEDS_FIX]

### Per-finding Status
1. Important (sweep ranks by IR): [FIXED / NOT FIXED]
2. Important (IR disclaimer): [FIXED / NOT FIXED]
3. Important (skip_no_qualifying_event): [FIXED / NOT FIXED]
4. Important (IR numerical pin): [FIXED / NOT FIXED]
5. Minor (indent): [FIXED / NOT FIXED]
6. Minor (redundant guard): [FIXED / NOT FIXED]
7. Minor (skip log summary): [FIXED / NOT FIXED]

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

Read-only. Do NOT modify.
