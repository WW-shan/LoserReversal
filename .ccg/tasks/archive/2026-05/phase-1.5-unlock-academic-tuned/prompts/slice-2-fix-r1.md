ROLE_FILE: /Users/ww/.claude/.ccg/prompts/codex/builder.md

# Phase 1.5 Slice 2 — Fix Round 1

## CRITICAL: Anti-monitor directive

- Do NOT tail/ps/grep for other codex processes. Start writing code IMMEDIATELY.
- Other codex processes belong to the user; UNRELATED to this task.
- Do NOT archive this task. Claude will archive after final LGTM.

## Working directory

`/Users/ww/Project/crypto-alpha-portfolio`

`uv run`, Python 3.11+, 100-char lines, UTC tz-aware, no emojis.

## Context

Slice 2 review converged on 2 Important + 1 Minor + 1 Recommendation. Fix all in one round with strict TDD pairs.

## Findings (union, deduped)

### IMPORTANT #1 — v1 backward-compat regression

`src/signals/_unlock_common.filter_events` now requires the full event schema:
```python
REQUIRED_EVENT_COLUMNS = {
    "token", "unlock_date", "unlock_pct", "category", "has_hl_perp", "vesting_type",
}
```

But the original `unlock_v1.unlock_short_signal` only required `{"token", "unlock_date", "unlock_pct"}` and conditionally `"has_hl_perp"`. The current code REGRESSES v1's contract: legacy callers passing minimal events now get empty results.

**Fix**:
- Make `REQUIRED_EVENT_COLUMNS` parameterized. Approach A (simpler): add `required_columns: set[str] | None = None` argument to `filter_events`. If `None`, defaults to the strict full set. If passed, uses the caller's set.
- v1 wrapper passes `required_columns={"token", "unlock_date", "unlock_pct", "has_hl_perp"}` so `category` and `vesting_type` are optional (v1 doesn't use them).
- v2/v3/v4/v5 wrappers pass `None` (use the strict default — they're new contracts that can demand the full schema).
- Add a test asserting v1 still works on a 4-col legacy DataFrame.

**Test additions**:
- `tests/signals/test_unlock_v1.py::test_works_on_legacy_event_schema_without_category_or_vesting_type`
- `tests/signals/test_unlock_common.py::test_filter_events_accepts_custom_required_columns`

### IMPORTANT #2 — Dual-mode API in `emit_pair_signals`

`emit_pair_signals` accepts EITHER `(entry_offset_days, exit_offset_days)` OR `(pre_window, post_window)`. Currently if both are passed, signed offsets silently win. Wrappers only use signed offsets, so the pre/post path is dead code.

**Fix**:
- Simplify the function: keep only `(entry_offset_days, exit_offset_days)`. Remove `pre_window` / `post_window` parameters entirely.
- Update `_resolve_offsets` accordingly — it can just verify both ints are provided and not None.
- Tests in `test_unlock_common.py` that exercise the pre_window/post_window path are no longer relevant — refactor them to use signed offsets.

**Test additions / changes**:
- Remove `test_emit_pair_signals_positive_post_window_works` (replace with `test_emit_pair_signals_positive_exit_offset_works` using signed offsets)
- Remove `test_emit_pair_signals_negative_pre_window_works` (replace with `test_emit_pair_signals_negative_entry_offset_works`)
- `test_emit_pair_signals_requires_both_offsets` — call with only `entry_offset_days` → ValueError mentioning both arg names

### MINOR #1 — Helper offset validation

`emit_pair_signals` doesn't check `exit_offset_days > entry_offset_days`. Wrappers do guard their windows, but a future direct caller could pass nonsense. Add a low-noise assertion.

**Fix**:
- In `emit_pair_signals` after `_resolve_offsets`: `if exit_offset <= entry_offset: raise ValueError(f"exit_offset_days ({exit_offset_days}) must be > entry_offset_days ({entry_offset_days})")`
- Test: `test_emit_pair_signals_rejects_non_increasing_offsets`

### RECOMMENDATION #1 — Cross-signal smoke test

Both reviewers suggested a single smoke test that runs all 5 signals against the same small fixture with coverage enabled. Cheap insurance against schema drift across versions.

**Fix**:
- New test `tests/signals/test_all_signals_smoke.py` with one parametrize-marked test that:
  - Builds a small `events` DataFrame (3 events, 3 tokens, 2 with `coverage_status='ok'`)
  - Builds a small `prices` dict with 60-day index
  - Builds a small `coverage` DataFrame
  - Calls each of v1/v2/v3/v4/v5 with `coverage=coverage`
  - Asserts result is non-empty for each (specific count check OK if you can compute it)

## Workflow (strict TDD)

Expected commit sequence (~7):

1. `test(signals): unlock helper accepts custom required event columns`
2. `feat(signals): unlock helper supports overridable required columns`
3. `test(signals): unlock_v1 works on legacy minimal event schema`
4. `feat(signals): unlock_v1 declares its legacy required column set`
5. `test(signals): emit_pair_signals requires both offsets and enforces ordering`
6. `feat(signals): drop pre/post_window dual mode and add offset validation`
7. `test(signals): cross-version coverage smoke`

After each commit:
- `uv run pytest -q` ≥ previous count
- `uv run ruff check src tests scripts data` clean

Final target: 255 → ~262 tests.

## Acceptance

- All 2 Important + 1 Minor + 1 Recommendation addressed
- pytest ≥ 262
- ruff clean
- v1 still works with 4-col legacy events (test proves it)
- emit_pair_signals public signature: `(events, prices, *, entry_offset_days, exit_offset_days)` only
- Helper validates exit > entry offset
- All-signals smoke test exists

## Out-of-scope guardrails

Do NOT:
- Touch backtest scripts (Slice 3)
- Modify infra/storage or data_audit (Slice 1 territory, frozen)
- Add new modules outside `src/signals/` and `tests/signals/`
- Push or archive

## Completion (Execution Report)

```
## Execution Report — Slice 2 Fix R1

### Findings addressed
- [x] Important #1 v1 backward-compat
- [x] Important #2 dual-mode API simplification
- [x] Minor #1 offset validation
- [x] Recommendation #1 cross-signal smoke

### Commits
- {sha} {subject}
...

### Pytest / Ruff
- baseline: 255
- final: {N}
- ruff: clean
```

EXIT. Do NOT archive. Do NOT push.
