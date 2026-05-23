ROLE_FILE: /Users/ww/.claude/.ccg/prompts/codex/reviewer.md

# Phase 1.5 Slice 2 — Code Review

## CRITICAL: Read-only

NO write permission. Output review report only.

## Working directory
`/Users/ww/Project/crypto-alpha-portfolio`

## What was implemented

5 academic-tuned unlock signal versions:
- v1 (refactored): T-7 → T0 short with optional coverage filter
- v2 (new): T-30 → T0 short (Keyrock long-swing window)
- v3 (new): T-2 → T+3 short (SmartKarma tactical cluster)
- v4 (new): T-72h → T0 short (Kim SSRN 72-hour)
- v5 (new): T+3 → T+14 reversal long (Keyrock — first time implemented)

Shared logic in `src/signals/_unlock_common.py` exposing:
- `filter_events(events, min_unlock_pct, require_hl_perp, coverage) -> DataFrame`
- `emit_pair_signals(events, prices, entry_offset_days, exit_offset_days OR pre_window, post_window) -> dict`

## Reading list

- `.ccg/tasks/phase-1.5-unlock-academic-tuned/prompts/slice-2-builder.md` (spec)
- `.ccg/tasks/phase-1.5-unlock-academic-tuned/plan.md`
- `docs/research/literature-review.md` Part A (academic source for each window)

## Git range

Use `git log --oneline 2f7719d..HEAD` to see the 14 new commits, then `git show <sha>` per commit.

## What to verify

### Plan alignment
- All 5 signal versions exist with expected window defaults?
- Each as separate module under `src/signals/`?
- v1 still works with existing tests + new coverage parameter?
- Shared helper is `_` prefixed (private)?
- v3 has independent `pre_window_days` AND `post_window_days`?
- v5 returns positive-offset entry (long after unlock)?

### Correctness
- `_unlock_common.emit_pair_signals` correctly handles:
  - negative entry_offset for shorts (-7, -30, -2, -3)
  - positive exit_offset for tactical/reversal (+3, +14)
  - overlap rule: second event entry must be > last exit (NOT just <)
- `filter_events` joins `coverage` on `(token, unlock_date)` correctly when both unlock_date types differ (datetime tz-aware vs date32)?
- Empty events / empty prices / missing columns → empty dict (not exception)?
- Invalid window param raises ValueError?
- UTC normalization preserved (no caller mutation)?

### Test quality
- TDD pairs: every feat preceded by test commit?
- Each signal module has all 10 standard test cases (mirror v1 coverage)?
- Tests check ACTUAL signal contents (entries.sum(), specific dates), not just `result != {}`?
- v3 has independent-pre/post test?
- v5 has post-unlock-entry assertion?

### Architecture
- Helper is reusable — no signal duplicates more than the thin wrapper itself?
- No cross-imports between signal modules (only shared via `_unlock_common`)?

### Production readiness
- `pytest -q` passes (255)?
- `ruff check src tests scripts data` clean?
- No dependencies added?
- No regressions in existing v1 / wallet_cluster / wallet_reverse signals?

## Output Format

### Strengths
[file:line specifics.]

### Issues

#### Critical (Must Fix)
[Bugs / spec violations.]

#### Important (Should Fix)
[Edge cases, weak tests.]

#### Minor (Nice to Have)
[Style polish.]

### Assessment
**Ready to merge into Slice 3?** [Yes | No | With fixes]
**Reasoning:** [2-3 sentences.]
