ROLE_FILE: /Users/ww/.claude/.ccg/prompts/codex/builder.md

# Phase 1 Slice 1 — Fix Review Findings

## CRITICAL: Anti-monitor directive
- Do NOT `tail`/`ps`/`grep` for other codex processes or log files.
- Start fixing IMMEDIATELY.

## Working directory
`/Users/ww/Project/crypto-alpha-portfolio`

Use `uv run pytest` and `uv run ruff` for all validation.

## Background

Codex reviewer scored Slice 1 at 85/100 NEEDS_FIX. Fix all 1 Critical + 4 Warnings below. Info items are optional — skip them unless trivially clean.

For each fix: write a regression test first (RED), then implement the fix (GREEN), commit separately.

## 1. CRITICAL — `walk_forward_splits` mode validation order

**File**: `src/infra/backtest/walkforward.py`

**Bug**: `mode` validation runs AFTER the `n_splits <= 0` early return. So `walk_forward_splits(start, end, n_splits=0, mode="invalid")` returns `[]` instead of raising `ValueError`.

**Fix**: move mode validation to the FIRST guard, before any other check. Order should be:
1. Validate `mode` in {"expanding", "rolling"}
2. Validate `n_splits >= 1`, `min_train_days >= 1`, `test_days >= 1` (also covers Warning 2)
3. Then feasibility check (span fits)
4. Then build splits

**Test to add** (in `tests/infra/test_walkforward.py`): assert that `walk_forward_splits(start, end, n_splits=0, mode="invalid")` raises `ValueError` (specifically about mode, not about n_splits — the ordering must surface the mode error first).

## 2. WARNING — `pre_window_days` not validated

**File**: `src/signals/unlock_v1.py`

**Fix**: at function entry, raise `ValueError` if `pre_window_days < 1`.

**Test to add** (in `tests/signals/test_unlock_v1.py`): `unlock_short_signal(events, prices, pre_window_days=0)` raises `ValueError`; `pre_window_days=-1` also raises.

## 3. WARNING — `min_train_days` / `test_days` not validated

**File**: `src/infra/backtest/walkforward.py` (already covered by fix #1 ordering item 2).

**Test to add**: `walk_forward_splits(..., min_train_days=0, ...)` raises ValueError; same for `test_days=0`.

## 4. WARNING — Price index UTC handling

**File**: `src/signals/unlock_v1.py`

**Fix**: when iterating `prices[token]`, coerce its `.index` to UTC tz-aware if it is naive (use `pd.DatetimeIndex(idx, tz="UTC")` when `idx.tz is None`; else `idx.tz_convert("UTC")`). This must NOT mutate the caller's Series — use a local coerced view for membership/lookup.

**Test to add**: a price Series with **naive** datetime index produces the same result as a UTC tz-aware version (the bug was that naive indexes silently skipped events).

## 5. WARNING — Trailing blank line at EOF

**File**: `src/signals/unlock_v1.py`

**Fix**: ensure the file ends with exactly one newline (no extra blank lines at EOF). Confirm with `git diff --check HEAD..HEAD~1` or similar.

No test for this — `ruff` and `git diff --check` cover it.

## Workflow

1. Write all new regression tests across `tests/signals/test_unlock_v1.py` and `tests/infra/test_walkforward.py` → confirm RED on the relevant ones → `git commit -m "test(slice-1): regression tests for review findings"`
2. Apply fix #1 + #3 (walkforward.py) → confirm GREEN → `git commit -m "fix(backtest): validate mode and positive ints in walk_forward_splits"`
3. Apply fix #2 + #4 + #5 (unlock_v1.py) → confirm GREEN → `git commit -m "fix(signals): validate pre_window_days and coerce UTC index"`

(3 commits total. If you find that #2 and #4 are cleaner as separate commits, that's fine — but keep test commit first.)

## Acceptance

- `uv run pytest tests/signals tests/infra/test_walkforward.py -q` → all green (was 16, will be ~20 after new tests)
- `uv run pytest -q` → all green (overall regression sweep, was 80, will be ~100)
- `uv run ruff check src tests` → clean

## Out of scope

- Do NOT touch Info items (docstring carry, exact tuple assertions) — keep diff minimal.
- Do NOT modify any other file.

## Completion

Print Execution Report with files changed, commit SHAs, final pytest output (last 5 lines), final ruff output, OVERALL PASS/FAIL.

Then EXIT. Do not "monitor" anything.
