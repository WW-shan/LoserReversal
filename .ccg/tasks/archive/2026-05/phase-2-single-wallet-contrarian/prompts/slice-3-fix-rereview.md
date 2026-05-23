ROLE_FILE: /Users/ww/.claude/.ccg/prompts/codex/reviewer.md

# Phase 2 Slice 3 Fix — Re-review

## CRITICAL: Read-only

NO write permission.

## Working directory
`/Users/ww/Project/crypto-alpha-portfolio`

## Context

Slice 3 round 1 scored Codex 77/100 + subagent With fixes (3 Critical + 4 Important + 2 Warning + 2 Minor). Fix added 13 commits:

- e3c989f / 92bad11 — Critical 1 (cluster dedup at identical timestamp)
- 477016d / a032dc2 — Critical 2 (emit cluster at max-size timestamp)
- 9778cf8 / 2fc1cbd — Important 4 (fallback warning logs)
- ea76570 / e7308e4 — Critical 3 (configured-vs-effective pairs + banner)
- fd7541b — Important docs (verdict reason taxonomy docstring)
- 5d7df5c — Warning (drop unused coin_universe)
- b01005b / d10c535 — Warning (promote underscore helpers + import boundary test)
- 71dd2eb — Minor (split tests by target module)

## Verify each finding

### Critical 1 — Dedup identical-timestamp cluster
- `git show 92bad11` — confirm `drop_duplicates(subset=["entry_time", "side"])` applied
- `git show e3c989f` — regression test for 3 wallets at same ts → exactly 1 event with cluster_size=3
- No `(entry_time, side)` duplicates in output

### Critical 2 — Max cluster_size emit
- `git show a032dc2` — verify emit at max-size timestamp within cooldown window (not first-reached)
- `git show 477016d` — test for 4 wallets at t=0/10/20/25 → 1 event at max-size point with cluster_size=4

### Critical 3 — Configured vs effective
- `cat reports/wallet_reverse_walkforward.md` — verify Walk-Forward Config shows pairs (e.g. `min_train_days: 120 (effective: 30)`)
- Banner `> [WARN] walk-forward fallback used` present below Verdict line when applicable

### Important 4 — Fallback warning logs
- `git show 2fc1cbd` — verify `_log("[WARN] walk-forward fallback: ...")` emitted on dimension shrinkage
- `git show 9778cf8` — regression test

### Important 5 — Verdict reason docstring
- `git show fd7541b` — verify `_verdict()` docstring documents 5-tier taxonomy (data_gap / insufficient_sample / insufficient_oos_trades / oos_ir_below_yellow / max_drawdown_breach / thresholds_not_met)

### Warning 6 — coin_universe removed
- `git show 5d7df5c` — verify removed from signature + tests + docstring

### Warning 7 — Helper promotion
- `git show d10c535` — verify `_filter_fills_by_end`, `_filter_fills_by_start`, `_coerce_utc_timestamp`, `_backtest_freq` → public names
- `git show b01005b` — verify regression test that prevents future private cross-script imports

### Minor 8 — Test split
- `git show 71dd2eb` — verify tests moved to correct files (test_run_wallet_reverse_backtest.py + test_run_wallet_cluster_backtest.py)

## Check for new issues

- Any test broken by helper rename?
- Cluster dedup logic doesn't accidentally drop legitimate separate clusters at different timestamps?
- Max-cluster-size emit logic: when does the algorithm decide a cluster window has "ended"? Cooldown-based?

## Output format

```
## Phase 2 Slice 3 Fix Re-Review

### Verdict
[LGTM (ready for archive + verdict commit) / STILL NEEDS_FIX]

### Per-finding Status
1. Critical (dedup): [FIXED with regression / NOT FIXED]
2. Critical (max cluster_size emit): [FIXED with regression / NOT FIXED]
3. Critical (configured vs effective): [FIXED / NOT FIXED]
4. Important (fallback warning): [FIXED with regression / NOT FIXED]
5. Important (verdict reason docstring): [FIXED / NOT FIXED]
6. Warning (coin_universe drop): [FIXED / NOT FIXED]
7. Warning (helper promotion): [FIXED with import boundary test / NOT FIXED]
8. Minor (test split): [FIXED / NOT FIXED]

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
