ROLE_FILE: /Users/ww/.claude/.ccg/prompts/codex/builder.md

# Phase 2 Slice 2 — Fix R3: subagent Minor polish (5 items)

## CRITICAL: Anti-monitor
- Do NOT tail/ps. Start IMMEDIATELY.
- Do NOT archive.

## Working directory
`/Users/ww/Project/crypto-alpha-portfolio`

## Background

Slice 2 fix R2 passed 3-way review (Codex 99/100, subagent Ready). 5 Minor polish items remain per repo policy "全部修好再进下一阶段". All non-blocking but should be cleaned before Slice 3.

## 5 Fixes

### Minor 1 — Sweep ranking test fixture discriminates IR vs Sharpe

**File**: `tests/scripts/test_sweep_wallet_holding.py:52-73` (`test_sweep_ranking_keeps_eligible_rows_before_ineligible_high_sharpe`)

Currently the fixture sets `sharpe == trade_level_ir` for every row, so the test passes whether ranking key is IR or Sharpe. Make at least 2 eligible rows where IR-rank vs Sharpe-rank differs:

```python
# Row A: high Sharpe, lower IR
{"holding_hours": 4, "n_trades": 1000, "sharpe": 99.0, "trade_level_ir": 2.0, ...},
# Row B: low Sharpe, higher IR
{"holding_hours": 12, "n_trades": 1000, "sharpe": 2.0, "trade_level_ir": 99.0, ...},
```

Then assert the ranking puts Row B before Row A (because IR is the gate metric).

### Minor 2 — Skip summary silent when no wallets

**File**: `scripts/run_wallet_reverse_backtest.py:110-117`

Wrap the `[skip summary]` print in `if wallets:` so empty-portfolio path doesn't emit `no_fills=0 no_open_dir=0 ...`.

### Minor 3 — `_has_non_null_time` docstring

**File**: `scripts/run_wallet_reverse_backtest.py:613-619`

Add a one-line docstring documenting the contract:

```python
def _has_non_null_time(frame: pd.DataFrame) -> bool:
    """Return True iff frame has a `time` column with non-null entries OR a DatetimeIndex
    with non-null entries. Frames missing both timeline shapes return False (no qualifying event)."""
```

### Minor 4 — Explain `_sort_sharpe` vs `_sort_eligible_ir` coexistence

**File**: `scripts/run_wallet_reverse_backtest.py:132`

Add inline comment at the line that uses `_sort_sharpe` for per-wallet rows:

```python
# Per-wallet rows continue to display by Sharpe descending; sweep ranking is by IR
# (see scripts/sweep_wallet_holding.py). Mixed sort keys are intentional.
```

### Minor 5 — Funnel markdown row single f-string

**File**: `scripts/run_wallet_reverse_backtest.py:505-506` (and similar nearby rows)

Combine the two-string adjacent concatenation into a single f-string:

```python
f"| skip_no_qualifying_event | {funnel['skip_no_qualifying_event']} | wallets with no qualifying signal event |",
```

Make it explicit single-line. If any other funnel rows use the same split pattern, fix them too for consistency.

## Workflow

3 commits (combine where natural):
1. `test(scripts): sweep ranking fixture distinguishes IR vs Sharpe`
2. `chore(scripts): docstring + comments for mixed sort keys`
3. `chore(scripts): tidy skip summary guard + funnel row formatting`

## Acceptance

- `uv run pytest -q` → 151+ tests pass
- `uv run ruff check src tests scripts` clean
- Test `test_sweep_ranking_keeps_eligible_rows_before_ineligible_high_sharpe` (or new test) actually asserts IR-ranked order, not just `eligible` order
- Empty-pool run produces no `[skip summary]` line

## Out of scope

- Cluster signal (Slice 3)
- Walk-forward (Slice 3)
- Daily/hourly Sharpe pin tests (future improvement)

## Completion

Execution Report with commits, final pytest output, ruff output. Then EXIT. Do NOT archive.
