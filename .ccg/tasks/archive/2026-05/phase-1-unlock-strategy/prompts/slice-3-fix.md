ROLE_FILE: /Users/ww/.claude/.ccg/prompts/codex/builder.md

# Phase 1 Slice 3 — Fix Review Findings (Round 1)

## CRITICAL: Anti-monitor directive
- Do NOT tail/ps/grep. Start fixing IMMEDIATELY.
- Do NOT archive the task this time — Claude will archive after final review LGTM.

## Working directory
`/Users/ww/Project/crypto-alpha-portfolio`

Use `uv run` for validation.

## Background

Slice 3 review (Codex + Claude) scored 67/100 BLOCK. Process + correctness issues:

1. Builder archived task before review approval (already reverted by Claude — do NOT re-archive)
2. Verdict reason `insufficient_sample` is misleading when n_trades=0 (it's a `data_gap`, not just a small sample)
3. 0-OOS-trade aggregate metrics shown as numeric `0.00` with PASS/GREEN status — meaningless
4. Boundary leak: `date_start >=` + `date_end <=` overlap on train_end / test_start
5. IS fallback chose 2-trade lucky-window configs that have no OOS coverage
6. ROADMAP only says "0 OOS trades" — should explain data_gap root cause

## Fixes (5 commits expected)

### Fix 1 — Verdict reason refinement (Critical #2)

**File**: `scripts/run_unlock_walkforward.py` (`_verdict` function)

Distinguish 3 RED reasons:
- `data_gap`: `oos_n_trades_total == 0` (no executable OOS events — data/window coverage problem)
- `insufficient_sample`: `0 < oos_n_trades_total < 15` (small but non-zero sample)
- `thresholds_not_met`: `oos_n_trades_total >= 15` but verdict still RED (real strategy underperformance)

Priority order in `_verdict()`:
```python
if oos_n_trades_total == 0:
    return Verdict("RED", "data_gap")
if oos_n_trades_total < 15:
    return Verdict("RED", "insufficient_sample")
# ... GREEN / YELLOW / thresholds_not_met
```

### Fix 2 — N/A aggregate metrics when 0 OOS trades (Critical #2 cont.)

**File**: `scripts/run_unlock_walkforward.py` (`_aggregate_rows` + helpers)

When `oos_n_trades_total == 0`:
- OOS Sharpe (mean) → `n/a` with Status `NO SAMPLE`
- OOS Sharpe (min/worst) → `n/a` with Status `NO SAMPLE`
- OOS Max DD (worst) → `n/a` with Status `NO SAMPLE`
- IS→OOS decay → `n/a` with Status `NO SAMPLE`
- OOS n_trades (total) → `0` with Status `FAIL` (this is real)

Do NOT show `PASS` / `GREEN` for metrics derived from zero samples. The current report (`Sharpe (min/worst) PASS`, `MaxDD GREEN`) is misleading.

### Fix 3 — Boundary leak fix (Warning #3)

**File**: `scripts/run_unlock_backtest.py` (date filter at lines 68-72)

Change OOS-side comparison to **strict** to avoid double-counting boundary events:

Option A (recommended — simpler): make `date_end` filter **exclusive** in the backtest:
```python
if config.date_end is not None:
    events = events.loc[events["unlock_date"] < config.date_end].copy()
```

This means a split with `train_end=2025-10-29, test_start=2025-10-29` will:
- IS includes events on 2025-10-28 and earlier (date_end exclusive = 2025-10-29)
- OOS includes events from 2025-10-29 onward
- An event exactly on 2025-10-29 belongs to OOS only — no double-counting.

Document this in the docstring: `date_end is exclusive; date_start is inclusive`.

Update tests in `tests/scripts/test_walkforward_runner.py` to cover this boundary behavior (one event exactly on the boundary, verify it ends up in OOS only).

### Fix 4 — IS fallback selection improvement (Warning #4)

**File**: `scripts/run_unlock_walkforward.py` (`_select_best_is_row`)

Current fallback: `max(rows, key=_sort_sharpe)` — selects max Sharpe regardless of n_trades.

Better fallback (when no eligible rows ≥ 30 trades):
1. Filter to rows with `n_trades > 0`.
2. Among those, prefer rows with `n_trades >= median(n_trades)` AND `sharpe > 0`.
3. Within that filtered set, pick max Sharpe.
4. If filter yields empty → fall back to max-Sharpe-with-positive-trades.
5. If still empty (all rows zero-trade) → fall back to original max-Sharpe with explicit log warning `[WARN] split N: no positive-trade IS config; fallback chose 0-trade max-Sharpe`.

Mark `eligible_in_is=False` in all fallback cases (already done).

Also add a new field `is_selection_mode` in the split result: `"eligible"` / `"positive_trades_median"` / `"positive_trades_any"` / `"zero_trade_fallback"` — surface in the per-split table.

### Fix 5 — ROADMAP text (Warning #5)

**File**: `docs/research/loser-reversal-indicator/ROADMAP.md`

Find the Phase 1 verdict section. Update text to mention:
- Verdict: RED (KILL)
- Reason: `data_gap` — OOS events filter down to unsupported tokens (LISTA) or out-of-candle-range windows
- Implication: cannot make a strategy edge claim from current 348-day data; rerun after 6+ months of additional unlock events would change the picture

Keep numbers accurate (mean OOS Sharpe = n/a, OOS trades = 0).

## Workflow

5 commits expected, in order:
1. `fix(walkforward): distinguish data_gap from insufficient_sample verdict reason`
2. `fix(walkforward): render n/a for zero-trade aggregate metrics`
3. `fix(backtest): make date_end filter exclusive to prevent boundary leak`
4. `fix(walkforward): smarter IS fallback selection avoiding zero-OOS configs`
5. `docs(roadmap): clarify Phase 1 data_gap root cause`

(If fixes 1+2 fold cleanly, you may combine them.)

## Acceptance

- `uv run python scripts/run_unlock_walkforward.py --report /tmp/unlock_wf_v2.md` exits 0
- Verdict reason = `data_gap` (since OOS trades likely still 0 given data sparsity)
- Aggregate stats show `n/a` for Sharpe / MaxDD / decay when oos_trades=0
- Per-split table shows `is_selection_mode` column with sensible values
- Boundary test passes in `tests/scripts/test_walkforward_runner.py`
- `uv run pytest -q` → 102+ tests pass
- `uv run ruff check src tests scripts` clean
- ROADMAP.md Phase 1 section reflects data_gap reasoning

## Out of scope

- Refetching LISTA candles (separate concern)
- Expanding data (future Phase 1.5)

## Completion

Execution Report with files changed, commits (5 expected), final pytest output, ruff output, the new verdict reason + n/a aggregate rendering excerpt (10 lines).

Then EXIT. **Do NOT archive the task** — Claude will archive after final LGTM.
