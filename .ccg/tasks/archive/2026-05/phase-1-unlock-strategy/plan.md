# Phase 1 — Token Unlock Strategy Implementation Plan

> Build on Phase 0 infrastructure. Implement, backtest, and walk-forward validate the
> unlock-short strategy using the revised hypothesis from thesis-check (T-7→T0 short).

**Goal**: ship `signals/unlock_v1.py` + full backtest + walk-forward validation. Output
a Pass/Kill verdict that decides whether unlock strategy enters the final portfolio.

**Hypothesis (from thesis-check, archived)**:
- Short window: **T-7 → T0** (entry T-7, exit T0)
- Mean abnormal return vs BTC: -8.21% (p=0.01, 87.5% events negative)
- Driver: supply-shock magnitude, not insider category specifically
- Original "post-event short" assumption was wrong — bounce, not dump

**Tech stack** (all from Phase 0):
- `infra.hyperliquid_client` — HL universe
- `infra.fetchers.candles` — price data (paginated, completeness-safe)
- `infra.storage` — DuckDB + Parquet
- `infra.backtest.{engine,risk}` — vbt wrapper + risk primitives
- `infra.pipeline` — fetch → store → backtest orchestrator
- `data/parquet/unlocks.parquet` — 126 events seed (from Phase 1 prep)

---

## Slices (each = one Codex builder run)

### Slice 1: Signal function + walk-forward scaffold (this run)

**Files**:
- Create `src/signals/__init__.py`
- Create `src/signals/unlock_v1.py` — pre-event short signal
- Create `src/infra/backtest/walkforward.py` — walk-forward split utility
- Create `tests/signals/__init__.py`
- Create `tests/signals/test_unlock_v1.py` — unit tests on signal generation
- Create `tests/infra/test_walkforward.py` — walk-forward correctness
- Modify `pyproject.toml` — add `src/signals` to wheel packages

**Acceptance**:
- `unlock_short_signal(events, prices)` returns (entries, exits) bool Series per token
- Walk-forward util: split (start, end) into N expanding/rolling windows
- TDD; all tests green; ruff clean

### Slice 2: Full backtest + parameter sweep (next run)

- `scripts/run_unlock_backtest.py` — single-config end-to-end run
- `scripts/sweep_unlock_params.py` — grid sweep over (window, unlock_pct_threshold, stop_loss)
- Inputs: data/parquet/unlocks.parquet + cached candles via pipeline
- Output: reports/unlock_v1_sweep.md with heatmap-style results

### Slice 3: Walk-forward validation + Pass/Kill decision (next run)

- `scripts/run_unlock_walkforward.py` — split data into IS/OOS windows, optimize IS, evaluate OOS
- Decision logic compares OOS metrics against task.json passCriteria
- Output: reports/unlock_v1_walkforward.md + Pass/Kill verdict

---

## Signal v1 spec (Slice 1)

```python
def unlock_short_signal(
    events: pd.DataFrame,        # columns: token, coingecko_id, unlock_date, unlock_pct, category, has_hl_perp
    prices: dict[str, pd.Series],  # token -> close price series (HL data, UTC-indexed)
    pre_window_days: int = 7,    # T-pre_window entry
    min_unlock_pct: float = 0.02,
    require_hl_perp: bool = True,
) -> dict[str, tuple[pd.Series, pd.Series]]:
    """
    For each token, produce (entries, exits) bool series aligned to price index.

    Logic:
      - Filter events: unlock_pct >= min_unlock_pct, has_hl_perp if required
      - For each event at date T0:
        - entry = True on T-pre_window_days
        - exit = True on T0 (next bar after unlock)
      - Multiple events on same token are handled (chronological)

    Returns:
      Dict mapping token -> (entries: bool Series, exits: bool Series) for use with run_backtest.
    """
```

**Test cases**:
1. Single event, single token → 1 entry on T-7, 1 exit on T0
2. Event below `min_unlock_pct` → no entry
3. Event with `has_hl_perp=False` and `require_hl_perp=True` → no entry
4. Two events on same token within 7 days → second entry only fires after first exit
5. Multiple tokens → returns dict with all tokens
6. Event date outside prices index → silently skipped (no error)

---

## Walk-forward spec (Slice 1)

```python
def walk_forward_splits(
    start: datetime,
    end: datetime,
    n_splits: int = 5,
    mode: str = "expanding",  # "expanding" or "rolling"
    min_train_days: int = 90,
    test_days: int = 60,
) -> list[tuple[tuple[datetime, datetime], tuple[datetime, datetime]]]:
    """
    Return list of ((train_start, train_end), (test_start, test_end)) tuples.
    Expanding: train_start fixed, train_end grows; test follows train_end.
    Rolling: both train_start and train_end shift.
    """
```

**Test cases**:
1. Expanding mode produces increasing train sizes
2. Rolling mode keeps train size constant
3. No overlap between train and test windows
4. n_splits respected
5. Total span doesn't exceed [start, end]

---

## Conventions

Same as Phase 0:
- TDD (test-first, separate commit per task)
- ruff clean (`uv run ruff check src tests scripts`)
- 100-char lines
- No premature abstraction
- DataFrames indexed by UTC datetime
- Commit messages follow `feat(signals): ...` / `feat(backtest): ...` / `test(signals): ...`

## Pass/Kill final criteria (Slice 3)

```yaml
pass:
  in_sample_sharpe: >= 1.0
  walk_forward_oos_sharpe: >= 0.7
  max_drawdown: <= 25%
  min_trades: 30

kill_actions:
  - Document failure mode in reports/
  - Skip to Phase 2 (single-wallet contrarian)
  - Update ROADMAP.md
```

If `walk_forward_oos_sharpe` is between 0.3 and 0.7, mark as WEAK — include in portfolio
with reduced weight.

---

## Out of scope (deferred)

- Live execution (Phase 6 paper trading)
- Cross-exchange arbitrage (Phase 3)
- ML feature engineering (potentially Phase 1.5 if WEAK)
