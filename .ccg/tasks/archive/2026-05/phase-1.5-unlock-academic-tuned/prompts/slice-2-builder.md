ROLE_FILE: /Users/ww/.claude/.ccg/prompts/codex/builder.md

# Phase 1.5 Slice 2 — 5 Signal Versions

## CRITICAL: Anti-monitor directive

- Do NOT tail/ps/grep for other codex processes. Start writing code IMMEDIATELY.
- Other codex processes belong to the user; UNRELATED to this task.
- Do NOT archive this task. Claude will archive after final LGTM.

## Working directory

`/Users/ww/Project/crypto-alpha-portfolio`

`uv run` everywhere. Python 3.11+, `from __future__ import annotations`, 100-char lines, UTC tz-aware, no emojis in code/commits.

## Required reading

- `docs/research/literature-review.md` Part A — window selection rationale
- `.ccg/tasks/phase-1.5-unlock-academic-tuned/plan.md` — Slice 2 spec
- `src/signals/unlock_v1.py` — existing v1 reference implementation
- `tests/signals/test_unlock_v1.py` — test style
- `src/infra/data_audit.py` — `coverage_status == 'ok'` filter is REQUIRED for all signals

## Goal of this slice

Implement 5 signal variants based on academic literature windows. Each variant is a separate function in a separate module under `src/signals/`. Each has a dedicated test file. Slice 3 will grid-sweep parameters; Slice 4 walk-forwards; this slice is about the signal primitives only.

Pre-event filter for all 5: use `data/parquet/event_coverage.parquet`. Only events with `coverage_status == 'ok'` are eligible (their token has ≥60 pre-event days of candles).

## The 5 signal versions

### v1 (already exists) — `src/signals/unlock_v1.py::unlock_short_signal`
- Window: T-7 → T0
- Direction: short
- Status: keep as-is for now. Add a tiny shim test asserting it still produces signals when given the coverage filter; otherwise do not modify.
- **DO add a `coverage` parameter (optional DataFrame) so v1 can join with `event_coverage.parquet` when given.** Default `None` = preserve current behavior (existing tests stay green).

### v2 — `src/signals/unlock_v2.py::unlock_short_30d`
- Window: T-30 → T0
- Direction: short (entry T-30, exit T0)
- Academic source: Keyrock 16k events (90% negative, T-30 anticipation)
- Same signature shape as v1: `(events, prices, pre_window_days=30, min_unlock_pct=0.02, require_hl_perp=True, coverage=None) -> dict[str, tuple[pd.Series, pd.Series]]`

### v3 — `src/signals/unlock_v3.py::unlock_short_tactical`
- Window: T-2 → T+3 (SmartKarma strongest cluster)
- Direction: short (entry T-2, exit T+3)
- Need both `pre_window_days=2` and `post_window_days=3` parameters
- Function signature: `(events, prices, pre_window_days=2, post_window_days=3, min_unlock_pct=0.02, require_hl_perp=True, coverage=None) -> dict[str, tuple[pd.Series, pd.Series]]`

### v4 — `src/signals/unlock_v4.py::unlock_short_72h`
- Window: T-72h → T0 (Kim SSRN 88.5% profit)
- Direction: short (entry T-3, exit T0)
- Same signature as v2 with `pre_window_days=3` default

### v5 — `src/signals/unlock_v5.py::unlock_reversal_long`
- Window: T+3 → T+14 (Keyrock reversal-long, never implemented)
- Direction: **long** (entry T+3, exit T+14)
- This is the academically-recommended bounceback play
- Signature: `(events, prices, post_entry_days=3, post_exit_days=14, min_unlock_pct=0.02, require_hl_perp=True, coverage=None) -> dict[str, tuple[pd.Series, pd.Series]]`
- Note: returns the same `(entries, exits)` tuple shape; vectorbt portfolio will treat it as long entries automatically via `Portfolio.from_signals(close, entries, exits, ...)` (we'll set direction in backtest).

## Shared helper (refactor)

To avoid duplication, extract a private helper module `src/signals/_unlock_common.py`:

```python
def filter_events(
    events: pd.DataFrame,
    *,
    min_unlock_pct: float,
    require_hl_perp: bool,
    coverage: pd.DataFrame | None,
) -> pd.DataFrame:
    """Apply common filters: pct threshold, has_hl_perp, coverage_status == 'ok'."""
    ...

def emit_pair_signals(
    *,
    events: pd.DataFrame,
    prices: dict[str, pd.Series],
    pre_window: pd.Timedelta,
    post_window: pd.Timedelta,
) -> dict[str, tuple[pd.Series, pd.Series]]:
    """Generic entry/exit signal emitter given window offsets relative to unlock_date."""
    ...

def coerce_bool_series(series: pd.Series) -> pd.Series:
    ...
```

- pre_window = how far BEFORE T0 to enter (positive Timedelta; for v5 reversal, pre_window=0)
- post_window = how far AFTER T0 to exit (positive Timedelta; for v1/v2/v4, post_window=0)
- For v5: entry at T+post_entry_days, exit at T+post_exit_days → emit_pair_signals takes a more general `(entry_offset, exit_offset)` from `unlock_date`

Recommended: parameterize as **entry_offset_days, exit_offset_days** (signed) relative to `unlock_date`. Then:
- v1: entry=-7, exit=0
- v2: entry=-30, exit=0
- v3: entry=-2, exit=+3
- v4: entry=-3, exit=0
- v5: entry=+3, exit=+14

Each module is a thin wrapper around the helper exposing the academic-named defaults.

## Scope (file list)

### Create
- `src/signals/_unlock_common.py` — shared filter + signal emitter
- `src/signals/unlock_v2.py` — short T-30 wrapper
- `src/signals/unlock_v3.py` — short T-2→T+3 wrapper
- `src/signals/unlock_v4.py` — short T-72h wrapper
- `src/signals/unlock_v5.py` — reversal long T+3→T+14 wrapper
- `tests/signals/test_unlock_common.py` — helper unit tests
- `tests/signals/test_unlock_v2.py`
- `tests/signals/test_unlock_v3.py`
- `tests/signals/test_unlock_v4.py`
- `tests/signals/test_unlock_v5.py`

### Modify
- `src/signals/unlock_v1.py` — add `coverage` parameter (optional) using the shared helper. Existing tests must still pass.
- `tests/signals/test_unlock_v1.py` — add one new test for coverage parameter behavior

### Do NOT modify
- Anything in `scripts/`
- `src/infra/`
- `data/`
- `reports/`
- `docs/`
- `.ccg/tasks/`

## Specifications per signal

### Shared invariants
1. Input: `events` DataFrame must have `token, unlock_date, unlock_pct, category, has_hl_perp, vesting_type`
2. Input: `prices` dict {token: pd.Series with DatetimeIndex tz=UTC, close prices}
3. Coverage filter: when `coverage` is provided (DataFrame from `event_coverage.parquet`):
   - Join events with coverage on `(token, unlock_date)`
   - Drop events where `coverage_status != 'ok'`
   - When `coverage` is None, no coverage filter is applied (back-compat)
4. Output: `dict[str, tuple[pd.Series, pd.Series]]` where each tuple is `(entries, exits)` aligned to that token's price index
5. Entry/exit dates must be IN the price index (skip events where they're not)
6. Overlap rule: for a given token, second event's entry must be > last exit
7. `pre_window_days < 1` (for short variants) raises ValueError
8. `post_window_days < 1` (for v3/v5 where applicable) raises ValueError
9. Empty events / empty prices / missing columns → empty dict

### v5 reversal-long specifics
- Entry offset = +N days (must be >= 1)
- Exit offset = +M days (must be > entry offset)
- Logically a "long" signal but stays in same tuple shape — Slice 4 backtest will set `direction='long'` for v5

## Test cases per signal (mirror v1's coverage)

For v2, v3, v4, v5 each:
1. Single event emits one (entry, exit) pair at expected offsets
2. Event below `min_unlock_pct` → empty dict
3. `require_hl_perp=True` excludes non-HL tokens
4. `require_hl_perp=False` includes them
5. Two spaced events emit two non-overlapping pairs
6. Overlapping second event is skipped
7. Multiple tokens — only qualifying ones returned
8. Event with entry/exit outside price index is skipped
9. Naive price index normalized to UTC (no caller mutation)
10. Invalid window param (e.g., `pre_window_days=0`) → ValueError

For v3 specifically: also test that `pre_window` and `post_window` can be set independently.
For v5 specifically: test that entry happens AFTER unlock_date (positive offset).

For helper `_unlock_common.py`:
- `test_filter_events_drops_low_pct`
- `test_filter_events_drops_non_hl_when_required`
- `test_filter_events_drops_failed_coverage_when_provided`
- `test_filter_events_no_op_when_coverage_none`
- `test_emit_pair_signals_aligns_to_price_index`
- `test_emit_pair_signals_skips_unalignable_event`
- `test_emit_pair_signals_negative_pre_window_works` (for shorts)
- `test_emit_pair_signals_positive_post_window_works` (for v5)
- `test_emit_pair_signals_skips_overlap`

## Workflow (strict TDD)

Expected commit sequence (~16):

1. `test(signals): shared unlock helper cases`
2. `feat(signals): shared unlock filter and signal emitter`
3. `refactor(signals): unlock_v1 uses shared helper with optional coverage`
4. `test(signals): unlock_v1 coverage filter`
5. `test(signals): unlock_v2 short T-30 cases`
6. `feat(signals): unlock_v2 short T-30 wrapper`
7. `test(signals): unlock_v3 short tactical T-2 T+3 cases`
8. `feat(signals): unlock_v3 short tactical wrapper`
9. `test(signals): unlock_v4 short 72h cases`
10. `feat(signals): unlock_v4 short 72h wrapper`
11. `test(signals): unlock_v5 reversal long T+3 T+14 cases`
12. `feat(signals): unlock_v5 reversal long wrapper`

After each commit:
- `uv run pytest -q` ≥ prior count
- `uv run ruff check src tests scripts data` clean

Target: 198 → ~245 tests.

## Acceptance

- All 5 signal functions exist and tested
- All v1 existing tests still green (refactor must not break them)
- v1, v2, v3, v4, v5 modules each importable: `from signals.unlock_vN import ...`
- Helper `_unlock_common.py` private (underscore prefix) — not imported outside `src/signals/`
- pytest ≥ 240 (198 + ~10 tests/signal × 4 + ~5 helper + 1 v1-coverage)
- ruff clean
- ~14-18 small TDD-paired commits, no monolithic commit

## Out-of-scope guardrails

Do NOT:
- Touch `scripts/run_unlock_*` (Slice 3-4 will add new runner scripts)
- Add backtest logic (Slice 3+)
- Write a grid sweep (Slice 3)
- Modify `data_audit.py` or any `infra/` file
- Add new dependencies
- Touch reports

## Completion (Execution Report)

```
## Execution Report — Slice 2

### Files touched
- {file}: {what changed}
...

### Commits
- {sha} {subject}
...

### Pytest / Ruff
- baseline: 198
- final: {N}
- ruff: clean

### Smoke test
- Each signal returns non-empty dict when fed 3 sample events + 60d candles:
  - v1: {N} tokens with signals
  - v2: {N} tokens with signals
  - v3: {N} tokens
  - v4: {N} tokens
  - v5: {N} tokens
```

Then EXIT. Do NOT archive. Do NOT push.
