ROLE_FILE: /Users/ww/.claude/.ccg/prompts/codex/builder.md

# Phase 2 Slice 2 — Fix Review Findings

## CRITICAL: Anti-monitor directive
- Do NOT tail/ps. Start IMMEDIATELY.
- Do NOT archive.
- **STRICT COMMIT GRANULARITY**: one commit per logical fix (test → impl). If you produce 1 monolithic commit again, that's a process violation. Aim for 5-7 commits this round.

## Working directory
`/Users/ww/Project/crypto-alpha-portfolio`

## Background

Slice 2 scored 71/100 NEEDS_FIX (Claude+Codex agreement). The original `-27 Sharpe` is hourly-frequency math correctness on dense equity curve — NOT a bug — but the report compares it to ROADMAP IR=1.2 which is trade-level. Need additional metrics to make the decision gate meaningful for Slice 3.

## 5 Fixes

### Fix 1 — Add trade-level IR (Critical)

**File**: `scripts/run_wallet_reverse_backtest.py`

Compute per-trade returns: for each trade `(entry_time, exit_time, side, notional)`:
- `trade_return = (exit_px - entry_px) / entry_px * (1 if side=="long" else -1)`
- After accounting for fees `2 * fees + 2 * slippage` deducted from notional return
- Trade-level IR = `mean(trade_returns) / std(trade_returns) * sqrt(annual_trade_freq)`
  - `annual_trade_freq = n_trades / total_days * 365`
  - Use `total_days` from `min(entry_time) → max(exit_time)`

Add `trade_level_ir` field to per-wallet stats AND portfolio stats. Report it next to existing Sharpe.

### Fix 2 — Add daily-resampled Sharpe (Critical)

**File**: same

Resample portfolio equity to **daily** frequency: `equity.resample("1D").last().dropna()` → returns → `sharpe_ratio(returns, periods_per_year("1D"))`.

Add `daily_sharpe` field. Report alongside hourly Sharpe with explicit labels.

### Fix 3 — Decision gate clarification (Critical, follow-up of #1+#2)

Update "Decision Gate Check" table in report:
- Change Sharpe row label to **"Trade-level IR"** with threshold `>= 1.2`, value from Fix 1.
- Add a row `"Daily Sharpe"` with threshold `>= 1.0` (informational; tighter than IR but still annualized) with value from Fix 2.
- Keep `"Hourly Sharpe (informational)"` row WITHOUT a PASS/FAIL — just show the raw value.

The "Hourly Sharpe" should NEVER drive a gate decision.

### Fix 4 — Skip reason buckets (Warning #3)

**File**: `scripts/run_wallet_reverse_backtest.py`

When iterating wallets, track:
- `skip_no_fills` — `read_fills(addr)` returned empty
- `skip_no_open_dir` — no `Open Long/Short` in fills
- `skip_no_retail_size` — fills exist but all outside `[$1k, $200k]`
- `skip_no_candle` — fills + size OK but coin candles unavailable
- `skip_no_valid_pair` — events exist but no valid (entry, exit) pair builds

Add these to funnel section as separate columns. Aggregate count must match `n_candidate_wallets - n_backtested_wallets - n_failed_wallets`.

### Fix 5 — Backtest runner / sweep regression tests (Warning #4)

**File**: `tests/scripts/test_run_wallet_reverse_backtest.py` (NEW)
**File**: `tests/scripts/test_sweep_wallet_holding.py` (NEW)

Each at least 3 cases:
- `test_run_wallet_reverse_backtest.py`:
  1. Empty wallets directory → exits cleanly, all-zero stats
  2. Mock 2 wallets with synthetic fills/candles → portfolio Sharpe + trade-level IR + daily Sharpe all computed
  3. Skip reason bucket counts correct on a mix of skip causes
- `test_sweep_wallet_holding.py`:
  1. 4 holding-hour combos run without crash
  2. Sweep table ranking respects eligible flag (n_trades >= 100)
  3. CLI flag validation rejects negative `--init-cash`

Use pytest-mock to mock storage / candle reads.

## Workflow

5-7 commits (strict per-task):
1. `test(scripts): backtest runner trade-level IR cases` (RED)
2. `feat(scripts): add trade-level IR + daily-resampled Sharpe` (GREEN)
3. `fix(scripts): update decision gate to use trade-level IR` (no new test needed; existing gate test still passes with new metric)
4. `feat(scripts): skip reason buckets in funnel`
5. `test(scripts): backtest + sweep runner regression`
6. (optional) `chore(reports): refresh wallet reverse reports with new metrics`

## Acceptance

- `uv run python scripts/run_wallet_reverse_backtest.py --top-wallet-n 50` exits 0
- New report shows:
  - `Trade-level IR | >= 1.2 | <value> | PASS or FAIL`
  - `Daily Sharpe | >= 1.0 | <value> | PASS or FAIL`
  - `Hourly Sharpe (informational) | n/a | <value> | n/a`
  - Funnel with 5 new skip reason rows
- `uv run pytest -q` → ≥ 144 + new tests pass
- `uv run ruff check src tests scripts` clean
- Sweep report also has trade-level IR column

## Out of scope

- Cluster signal (Slice 3)
- Walk-forward (Slice 3)
- Refetching more wallets

## Completion

Execution Report with files changed, commit SHAs (5-7), final pytest output, ruff output, new portfolio numbers:
- trade-level IR value
- daily Sharpe value
- hourly Sharpe (existing -27 should not change)
- skip reason breakdown

Then EXIT. Do NOT archive.
