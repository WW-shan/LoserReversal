ROLE_FILE: /Users/ww/.claude/.ccg/prompts/codex/builder.md

# Phase 1 Slice 1 — TDD Builder Task

## CRITICAL: Anti-monitor directive

- Do NOT `tail`, `tail -f`, or read any log file under `/tmp/`.
- Do NOT run `ps aux`, `ps -ef`, or check if other codex processes exist.
- Other codex processes belong to the user and are UNRELATED to this task.
- There is NO existing work-in-progress for this slice. Start fresh.
- Begin writing code IMMEDIATELY. Do not "verify" or "monitor" first.
- If you find yourself wanting to check process state — STOP and start coding instead.

## Working directory
`/Users/ww/Project/crypto-alpha-portfolio`

Use `uv run pytest` and `uv run ruff` for all validation. Strict TDD.

## Scope (DO NOT exceed)

Create exactly these files:
- `src/signals/__init__.py` — empty marker
- `src/signals/unlock_v1.py` — pre-event short signal
- `src/infra/backtest/walkforward.py` — walk-forward split utility
- `tests/signals/__init__.py` — empty marker
- `tests/signals/test_unlock_v1.py` — unit tests on signal
- `tests/infra/test_walkforward.py` — walk-forward correctness tests

Modify:
- `pyproject.toml` — append `"src/signals"` into `[tool.hatch.build.targets.wheel] packages` (currently `["src/unlock_validation", "src/infra"]`)

## Specifications

### `unlock_short_signal`

```python
def unlock_short_signal(
    events: pd.DataFrame,            # cols: token, coingecko_id, unlock_date, unlock_pct, category, has_hl_perp
    prices: dict[str, pd.Series],    # token -> close price series (UTC tz-aware index)
    pre_window_days: int = 7,
    min_unlock_pct: float = 0.02,
    require_hl_perp: bool = True,
) -> dict[str, tuple[pd.Series, pd.Series]]:
    """
    For each token, produce (entries, exits) bool series aligned to that token's prices.index.

    Logic:
      - Filter events: unlock_pct >= min_unlock_pct; if require_hl_perp then has_hl_perp must be True.
      - For each remaining event at date T0:
          entry = True on (T0 - pre_window_days)
          exit  = True on T0
      - Multiple events on same token (chronological): a second event's entry is only emitted if its
        entry_date >= previous event's exit_date (no overlap with previously-open trade).
      - If T0 or (T0 - pre_window_days) is outside prices.index, silently skip that event.
      - If a token has no qualifying events, omit it from the returned dict.

    Returns dict[token, (entries: bool Series, exits: bool Series)] aligned to prices[token].index.
    """
```

### `walk_forward_splits`

```python
def walk_forward_splits(
    start: datetime,
    end: datetime,
    n_splits: int = 5,
    mode: str = "expanding",   # "expanding" or "rolling"
    min_train_days: int = 90,
    test_days: int = 60,
) -> list[tuple[tuple[datetime, datetime], tuple[datetime, datetime]]]:
    """
    Returns list of n_splits ((train_start, train_end), (test_start, test_end)) tuples.

    - Expanding: train_start fixed at `start`, train_end grows by `test_days` each split,
      test = (train_end, train_end + test_days).
    - Rolling: train window keeps constant size = min_train_days; both train_start and train_end
      shift by `test_days` each split.
    - test_start == train_end (no overlap, no gap).
    - All windows must fit within [start, end].
    - If [start, end] is too short to fit `n_splits` valid splits → raise ValueError.
    - Unknown mode → raise ValueError.
    """
```

## Test cases (write FIRST, fail, then implement — TDD)

### `tests/signals/test_unlock_v1.py`

1. Single event, single token, T0 in middle of prices index → 1 entry on T-7, 1 exit on T0
2. Event with `unlock_pct < min_unlock_pct` → token omitted from dict
3. Event with `has_hl_perp=False` and `require_hl_perp=True` → token omitted
4. Event with `has_hl_perp=False` and `require_hl_perp=False` → token included
5. Two events on same token spaced ≥ `pre_window_days` apart → two non-overlapping (entry, exit) pairs
6. Two events on same token within `pre_window_days` → only the FIRST pair fires
7. Multiple tokens, mixed eligibility → returned dict has only qualifying tokens
8. Event T0 outside prices.index → that event silently skipped; other events still processed

### `tests/infra/test_walkforward.py`

1. Expanding mode: train_end sequence is strictly increasing
2. Rolling mode: (train_end - train_start) constant across splits
3. For every split: test_start == train_end (no overlap)
4. `len(result) == n_splits`
5. Last split's test_end ≤ `end`
6. Span too short to fit `n_splits` → ValueError
7. mode="invalid" → ValueError

## Conventions (mirror Phase 0 code)

- Python 3.11+, pandas
- `from __future__ import annotations` at file top
- 100-char lines (`tool.ruff.line-length = 100`)
- UTC tz-aware datetimes throughout
- No emoji in code or commits
- Defensive guards: empty inputs return `{}` / `[]`; never raise on missing-data edge cases
- Reference style: `src/infra/backtest/engine.py`, `src/infra/backtest/risk.py`, `src/infra/storage.py`

## Workflow (strict TDD, ~6 commits)

For unlock_v1:
1. Write `tests/signals/test_unlock_v1.py` + `tests/signals/__init__.py` (RED) → `git commit -m "test(signals): unlock_v1 test cases"`
2. Confirm `uv run pytest tests/signals/test_unlock_v1.py -q` fails as expected
3. Write `src/signals/unlock_v1.py` + `src/signals/__init__.py` (minimal impl, GREEN)
4. Confirm tests pass + `uv run ruff check src tests` clean
5. `git commit -m "feat(signals): unlock_short_signal T-N→T0 entry/exit"`

For walkforward:
6. Write `tests/infra/test_walkforward.py` (RED) → `git commit -m "test(backtest): walk_forward_splits cases"`
7. Confirm fail
8. Write `src/infra/backtest/walkforward.py` (GREEN)
9. Confirm pass + ruff clean
10. `git commit -m "feat(backtest): walk_forward_splits expanding/rolling"`

Plus:
11. Edit `pyproject.toml` (add `src/signals` to wheel packages) → `git commit -m "chore: include signals package in wheel build"`

Final validation:
- `uv run pytest tests/signals tests/infra/test_walkforward.py -q` → all green
- `uv run ruff check src tests` → clean

## Completion

Print the Execution Report (per builder.md format) including:
- Files changed
- Commit SHAs (short)
- Final pytest output (last 5 lines)
- Final ruff output

Then EXIT. Do not proceed to Slice 2. Do not "monitor" anything.
