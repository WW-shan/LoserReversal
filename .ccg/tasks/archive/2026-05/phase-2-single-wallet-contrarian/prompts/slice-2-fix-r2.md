ROLE_FILE: /Users/ww/.claude/.ccg/prompts/codex/builder.md

# Phase 2 Slice 2 — Fix Round 2 (4 Important + 3 Minor)

## CRITICAL: Anti-monitor directive
- Do NOT tail/ps. Start IMMEDIATELY.
- Do NOT archive.
- **STRICT COMMIT GRANULARITY**: one commit per logical fix (test → impl). 6-8 commits this round.

## Working directory
`/Users/ww/Project/crypto-alpha-portfolio`

Use `uv run` for validation.

## Background

Slice 2 round-1 fix scored Codex LGTM 94/100, but superpowers code-review subagent surfaced 4 Important + 3 Minor issues (Claude's earlier Critical was actually misinterpreted — see #2 below). All addressed in this round.

## Fixes

### Important 1 — Sweep ranks by hourly Sharpe, should rank by trade-level IR

**Files**: `scripts/sweep_wallet_holding.py`

- `_sort_eligible_sharpe` → rename to `_sort_eligible_ir`, sort by `row['trade_level_ir']` (with `math.isfinite` guard)
- "Decision Gate Summary" line: "Best holding by **Trade-level IR**" not "by Sharpe"
- `_best_summary` should print `IR ... | Sharpe ... | n_trades ...` (IR is the gate metric, Sharpe contextual)

### Important 2 — Trade-level IR disclaimer for overlapping positions

**Files**: `scripts/run_wallet_reverse_backtest.py` (`_write_report`)

Add a note in the "Portfolio Stats" section header, above the Trade-level IR row:

> Note: Trade-level IR aggregates each (entry, exit) pair's gross return as if trades were independent. For overlapping/concurrent positions on the same coin, the realized equity-curve metrics (Daily Sharpe, Hourly Sharpe, Max DD) are authoritative.

Place this note as a single italic paragraph between the section heading and the stats table.

### Important 3 — `_skip_reason_for_empty_events` fallthrough false-labels NaN-time/coin

**Files**: `scripts/run_wallet_reverse_backtest.py` (`_skip_reason_for_empty_events`, around line 576-595)

Currently the fallthrough returns `"skip_no_valid_pair"` even when `entry_time` or `coin` are NaN. Logic should be:

1. Check `time` column missing or all-NaN → return `"skip_no_qualifying_event"` (new bucket name)
2. Check `coin` all-NaN → same `"skip_no_qualifying_event"`
3. Existing checks for dir, retail size remain
4. Final fallthrough → `"skip_no_qualifying_event"` (rename from `skip_no_valid_pair` because we no longer reach "tried to build pair but failed"; the events frame is empty before pairing)

Update funnel column names accordingly. Update test `test_skip_reason_bucket_counts_match_non_backtested_wallets` and any related.

### Important 4 — Pin numerical correctness in integration test

**Files**: `tests/scripts/test_run_wallet_reverse_backtest.py`

Add at least one assertion of form:
```python
assert stats["trade_level_ir"] == pytest.approx(expected, rel=1e-3)
```
in `test_synthetic_wallets_compute_hourly_sharpe_trade_level_ir_and_daily_sharpe`. Compute `expected` by hand from the synthetic 6-trade scenario in the fixture. Document the calculation in a comment.

Alternative (simpler): add a separate test `test_per_trade_return_uses_direction_and_net_of_fees` that calls `_run_path_backtest` directly with 2 known trades and verifies the resulting per-trade return values exactly.

### Minor 5 — `_empty_coin_result` indentation

**Files**: `scripts/run_wallet_reverse_backtest.py:396-413`

Re-indent uniformly (likely 8-space).

### Minor 6 — `_trade_level_ir` redundant guard

**Files**: `scripts/run_wallet_reverse_backtest.py:613-614`

Remove the `len(returns) < 2` early return (the `math.isclose(volatility, 0.0)` branch handles single-trade case). Add inline comment if you keep it for defensive intent.

### Minor 7 — Skip log noise

**Files**: `scripts/run_wallet_reverse_backtest.py` (loop logging around line 85, 92, 100)

Replace per-skip stderr lines with a summary line at end of loop:
```
[skip summary] no_fills=34 no_open_dir=0 no_retail_size=1 no_candle=0 no_qualifying_event=0
```

Keep per-wallet success lines (`[3/50] backtested 0xabc...`) as-is.

## Workflow

7 commits (strict):
1. `fix(scripts): sweep ranks by trade_level_ir not hourly Sharpe`
2. `docs(reports): IR overlap disclaimer in portfolio stats`
3. `test(scripts): skip_reason precise bucket labels` (RED)
4. `fix(scripts): rename skip_no_valid_pair → skip_no_qualifying_event with NaN-aware logic` (GREEN)
5. `test(scripts): pin trade_level_ir numerical correctness`
6. `style(scripts): re-indent _empty_coin_result`
7. `fix(scripts): collapse skip logs to single summary line`

(Combine 6+7 if minor; 8+ commits OK if cleaner.)

## Acceptance

- `uv run python scripts/run_wallet_reverse_backtest.py --top-wallet-n 50` exits 0
  - Report has IR disclaimer above Trade-level IR row
  - Funnel uses `skip_no_qualifying_event` instead of `skip_no_valid_pair`
  - Skip summary line printed once at end of loop, not per-wallet
- `uv run python scripts/sweep_wallet_holding.py --top-wallet-n 50` exits 0
  - "Best holding by Trade-level IR" in Decision Gate Summary
  - Sweep ranking ordered by IR (not Sharpe)
- `uv run pytest -q` → ≥ 151 + new pin test, all pass
- `uv run ruff check src tests scripts` clean

## Out of scope

- Cluster signal (Slice 3)
- Walk-forward (Slice 3)
- Recomputing IR on de-overlapped trades (Slice 3 if needed)
- Refetching more wallets

## Completion

Execution Report with files changed, commit SHAs (6-7), final pytest output, ruff output, snippets showing:
- Updated sweep "Best holding by Trade-level IR" line
- Updated IR disclaimer in backtest report
- New `skip_no_qualifying_event` bucket
- Numerical assertion in integration test

Then EXIT. Do NOT archive.
