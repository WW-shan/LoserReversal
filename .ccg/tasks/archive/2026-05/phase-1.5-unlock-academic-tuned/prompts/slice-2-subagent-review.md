ROLE_FILE: /Users/ww/.claude/.ccg/prompts/codex/reviewer.md

# Phase 1.5 Slice 2 — Senior Reviewer

## CRITICAL: Read-only

NO write permission. Output review report only.

## Working directory
`/Users/ww/Project/crypto-alpha-portfolio`

## What Was Implemented

5 academic-tuned unlock signal modules + shared helper. v1 refactored to use the helper while staying backward-compatible. New v2 (T-30), v3 (T-2→T+3), v4 (T-72h), v5 (T+3→T+14 reversal-long).

## Requirements / Plan

- `.ccg/tasks/phase-1.5-unlock-academic-tuned/prompts/slice-2-builder.md`
- `.ccg/tasks/phase-1.5-unlock-academic-tuned/plan.md`

## Git Range to Review

**Base:** `2f7719d` (last Slice 1 commit)
**Head:** `eed435f` (current HEAD as of Slice 2 completion)

```bash
git diff --stat 2f7719d..HEAD
git diff 2f7719d..HEAD -- src/signals/ tests/signals/
```

## What to Check

You are a Senior Code Reviewer with expertise in software architecture, design patterns, and quantitative trading systems. Review against plan and identify issues before they cascade into Slice 3 grid sweep.

**Plan alignment:**
- All 5 signal modules present with academic-correct windows?
- Each test file ≥ ~10 test cases mirroring v1 coverage breadth?
- v3 / v5 properly handle pre+post window pair (not just single window)?

**Code quality:**
- The `emit_pair_signals` API allows either `(entry_offset_days, exit_offset_days)` OR `(pre_window, post_window)` — is this dual API justified, or unnecessary complexity?
- Coverage join handles tz vs date mismatch correctly? (`event_coverage.parquet` stores `unlock_date` as date, the signals filter probably has it as Timestamp — does the merge actually work?)
- Overlap rule consistency across all 5 signals — does v5 (post-event) handle it correctly?
- v1 backward-compat: existing test suite still pass after refactor?

**Architecture:**
- Helper truly shared (not just imported with copy-paste)?
- Private module (underscore prefix) — used outside `src/signals/`?
- No circular imports?

**Testing:**
- TDD pairs in commit history?
- Tests assert on real signal contents (specific dates, counts), not just non-empty?
- Edge cases: empty events, missing prices, NaN unlock_pct, wrong unlock_date type?
- A v3 test that pre and post can be set independently?
- A v5 test that verifies entry is AFTER unlock?

**Production readiness:**
- `uv run pytest -q` count? Should be 255.
- `uv run ruff check src tests scripts data` clean?
- No new dependencies?

## Output Format

### Strengths
[file:line specifics.]

### Issues

#### Critical (Must Fix)
[Bugs, spec violations, data-loss risks.]

#### Important (Should Fix)
[Architectural issues, missing pieces, test gaps.]

#### Minor (Nice to Have)
[Polish.]

For each issue: file:line + what + why + how to fix.

### Recommendations
[Process / future-proofing.]

### Assessment
**Ready to merge into Slice 3?** [Yes | No | With fixes]
**Reasoning:** [2-3 sentences.]
