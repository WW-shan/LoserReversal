ROLE_FILE: /Users/ww/.claude/.ccg/prompts/codex/reviewer.md

# Phase 1 Slice 3 — Code Review

## CRITICAL: Read-only

NO write permission. Do NOT modify files.

## Working directory
`/Users/ww/Project/crypto-alpha-portfolio`

## What to review

5 new commits introduced by Slice 3:
- `84e487c feat(scripts): date-range filter in unlock backtest config`
- `060c181 feat(scripts): unlock walk-forward validation runner`
- `723fa61 docs(roadmap): phase 1 verdict from walk-forward run`
- `f3af268 chore(reports): seed walkforward.md from real run`
- `8ea6edb chore: archive ccg task phase-1-unlock-strategy` ← **builder did this WITHOUT review approval; flag as process violation**

Use `git show 84e487c 060c181 723fa61 f3af268 8ea6edb` and inspect:
- `scripts/run_unlock_walkforward.py`
- `scripts/run_unlock_backtest.py` (date_start/date_end additions)
- `scripts/sweep_unlock_params.py` (passthrough of date range)
- `reports/unlock_v1_walkforward.md`
- `docs/research/loser-reversal-indicator/ROADMAP.md`

## Spec to validate against

`.ccg/tasks/archive/2026-05/phase-1-unlock-strategy/prompts/slice-3-builder.md` (Slice 3 builder prompt, archived).

## Suspicious result — INVESTIGATE

Builder reports verdict RED with reason `insufficient_sample`. But the aggregate stats:
- OOS Sharpe (mean) = 0.00
- OOS Sharpe (min/worst) = 0.00
- OOS n_trades (total) = 0
- IS→OOS decay = 100%

**Zero OOS trades is suspicious.** Data has 83 has_hl_perp events over 348 days. With 3 splits × 60 test_days = 180 OOS days, the OOS window should contain ~40 events. If 0 trades fired, possible bugs:
1. `date_start` / `date_end` filter is comparing tz-aware vs tz-naive datetimes silently producing empty filter
2. Walk-forward split bounds calculated from wrong start (e.g. fixed `2025-01-01` instead of `events.unlock_date.min()`)
3. OOS run uses IS best config but the IS phase always picks `min_unlock_pct=0.05` or similar high-filter param that gives 0 trades in OOS
4. The signal function's `(unlock_date - pre_window_days)` falls outside the test_window prices

**Your job: inspect actual numbers and explain why OOS trades = 0**. If this is a bug, this is a Critical issue. If it's a true reflection of data sparsity (e.g. all OOS events are out-of-range), document it clearly.

## Review focus

### Critical (must-fix before archive is justified)
1. **OOS trades = 0 root cause**: bug or data reality?
2. **Builder archived task without review approval** (commit 8ea6edb) — process violation flag. The CCG flow requires Claude+Codex reviewer LGTM before archive. Recommend reverting 8ea6edb until review concludes.
3. **Verdict correctness**: even if OOS=0 is correct, is `insufficient_sample` the right verdict? Or should it be `data_gap` (different reason)?

### Warnings
4. **Date-range filter implementation**: are tz-aware/naive comparisons consistent? Check `scripts/run_unlock_backtest.py:date_start/date_end` filter line.
5. **walk_forward_splits start point**: what's the actual `start` passed to it? Is it `events.unlock_date.min()` or something else? If it skips early events, OOS may miss data.
6. **IS optimization fallback logic**: when 0 eligible IS rows, how does it pick `is_best_config`? Does it pick max-Sharpe-overall regardless of n_trades, possibly always picking the 0-trade row?
7. **ROADMAP update accuracy**: does the verdict reasoning in ROADMAP.md align with the walkforward report?

### Info
8. Test coverage for date-range filter / walk-forward runner
9. Report markdown rendering

## Output format

```
## Slice 3 Review

### Summary
[overall + ROOT CAUSE of OOS=0]

### Critical Issues (count: N)
- ...

### Warnings (count: N)
- ...

### Info (count: N)
- ...

### Positive Notes
- ...

### Scoring
- Spec coverage: XX/20
- Correctness: XX/20
- Result validity: XX/20  (does the verdict reflect reality, or is it confounded by a bug?)
- Code quality: XX/15
- Style consistency: XX/15
- Process compliance: XX/10  (did builder follow review-first-then-archive flow?)

TOTAL: XX/100

RECOMMENDATION: [LGTM (verdict stands) / NEEDS_FIX (verdict not trustworthy) / BLOCK (process violation requires revert)]
```

Investigate with code reading + actual numbers — do NOT modify files.
