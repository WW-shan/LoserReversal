ROLE_FILE: /Users/ww/.claude/.ccg/prompts/codex/builder.md

# Phase 1 Slice 2 — Full Backtest + Parameter Sweep

## CRITICAL: Anti-monitor directive
- Do NOT tail/ps/grep for other codex processes.
- Other codex processes belong to the user; UNRELATED to this task.
- Start writing code IMMEDIATELY.

## Working directory
`/Users/ww/Project/crypto-alpha-portfolio`

Use `uv run` for all execution.

## Goal

Use Phase 0 infra + Slice 1 signal to backtest the unlock-short strategy on real HL candle data + 126 events in `data/parquet/unlocks.parquet`. Produce numbers for Slice 3 to decide Pass/Kill.

## Scope (DO NOT exceed)

Create:
- `scripts/run_unlock_backtest.py` — single-config end-to-end CLI
- `scripts/sweep_unlock_params.py` — parameter grid sweep CLI
- `reports/.gitkeep` if `reports/` dir doesn't exist (otherwise omit)

Modify: NONE (script-only slice).

## Architectural decisions (use these, do NOT redesign)

### Single-config flow (`run_unlock_backtest.py`)

1. Load `data/parquet/unlocks.parquet` via `infra.storage.read_unlocks()`
2. Filter rows where `has_hl_perp == True`
3. Determine date span: `start = events.unlock_date.min() - 30 days`, `end = events.unlock_date.max() + 7 days`
4. Tokens to fetch = `events.token.unique()`
5. For each token:
   - Try `infra.storage.read_candles(token, interval, start, end)`. On FileNotFoundError / OSError / duckdb error / range gap → `infra.fetchers.candles.fetch_candles(token, interval, start, end, client=HyperliquidClient())` then `write_candles`. Re-read.
   - On HL fetcher error (token not on HL despite `has_hl_perp=True` flag): log warning, skip token.
6. Build `prices: dict[token, pd.Series]` of `close` columns.
7. Call `unlock_short_signal(events, prices, pre_window_days=..., min_unlock_pct=..., require_hl_perp=True)`.
8. For each token in the returned signal dict:
   - `run_backtest(prices[token], entries, exits, BacktestConfig(direction="shortonly", init_cash=..., fees=..., slippage=..., freq="1D"))`
9. Aggregate (KISS choice — pick this exact approach):
   - For each token: capture (sharpe, sortino, max_dd, n_trades, total_return, win_rate, equity_final).
   - Portfolio Sharpe = the Sharpe of the *summed equity curve* across tokens (reindex/align on union date index, ffill, sum).
   - Portfolio MaxDD = MaxDD of the summed equity curve.
   - Total n_trades = sum across tokens.
   - Win rate = trades_won_sum / n_trades_sum.
10. Write report to `--report PATH` (default `reports/unlock_v1_backtest.md`):
   - Header: config summary (pre_window_days, min_unlock_pct, fees, slippage, freq, n_tokens, n_events_with_signal).
   - Portfolio-level stats table.
   - Per-token stats table (sorted by Sharpe desc).
   - Equity curve text-only (e.g. monthly date | summed equity dollars).

### CLI (run_unlock_backtest.py)

argparse with flags:
- `--pre-window-days INT` (default 7)
- `--min-unlock-pct FLOAT` (default 0.02)
- `--interval STR` (default "1d")
- `--init-cash FLOAT` (default 10000)
- `--fees FLOAT` (default 0.0005)
- `--slippage FLOAT` (default 0.0002)
- `--report PATH` (default `reports/unlock_v1_backtest.md`)

Use `--require-hl-perp` is implicit True (already filtered).

### Sweep (`sweep_unlock_params.py`)

Grid:
- `pre_window_days ∈ {3, 5, 7, 10, 14}`
- `min_unlock_pct ∈ {0.01, 0.02, 0.03, 0.05}`
- 20 combinations.

Reuse the single-config code path: refactor `run_unlock_backtest.py` to expose a `run_unlock_backtest(config: UnlockBacktestConfig) -> dict` function that returns the portfolio stats dict. Both scripts import it.

Output `reports/unlock_v1_sweep.md`:
- Heading: total combinations, runtime
- Table sorted by Sharpe desc:
  ```
  | rank | pre_window | min_pct | sharpe | sortino | max_dd | n_trades | win_rate | total_return |
  ```

CLI flags:
- `--interval STR` (default "1d")
- `--init-cash FLOAT` (default 10000)
- `--fees FLOAT` (default 0.0005)
- `--slippage FLOAT` (default 0.0002)
- `--report PATH` (default `reports/unlock_v1_sweep.md`)

### Per-token stats helper

Use `infra.backtest.risk.{sharpe_ratio, sortino_ratio, max_drawdown}` on `BacktestResult.equity` for consistency. Use `BacktestResult.stats` if it already has them (check what engine.py emits).

### Progress logging

Print to stderr while iterating tokens:
- `[3/26] fetching APE candles from HL... cached=False (12.3s)`
- `[3/26] signal generated: 2 trades`
- `[3/26] backtest: Sharpe=-0.42 MaxDD=-8.1%`

Print to stderr while iterating sweep grid:
- `[5/20] pre=7 min=0.02 → Sharpe=0.83 (45.2s)`

## Conventions

- `from __future__ import annotations`
- 100-char lines (`ruff line-length=100`)
- argparse with type-checked params
- Skip tokens with no candle data: log warning, continue
- Skip tokens with no signal in dict: don't include in per-token table
- No emoji in code or commits

## Tests

Skip unit tests for scripts (thin orchestrators over already-tested infra). Validate via real runs.

## Workflow

1. Write `scripts/run_unlock_backtest.py`, expose `run_unlock_backtest(config)` function + `main()` CLI wrapper → `git commit -m "feat(scripts): unlock backtest e2e runner"`
2. Real run: `uv run python scripts/run_unlock_backtest.py --report /tmp/unlock_e2e.md` (this WILL fetch HL data for ~30 tokens, may take 5-15 min)
3. Inspect `/tmp/unlock_e2e.md` for sanity (Sharpe in plausible range, n_trades > 30)
4. Write `scripts/sweep_unlock_params.py` importing the helper → `git commit -m "feat(scripts): unlock param grid sweep"`
5. Real run sweep: `uv run python scripts/sweep_unlock_params.py --report /tmp/unlock_sweep.md` (20 backtests, data already cached so ~30-60s)
6. Inspect `/tmp/unlock_sweep.md`

## Acceptance

- `uv run python scripts/run_unlock_backtest.py --report /tmp/unlock_e2e.md` exits 0, produces a populated report
- `uv run python scripts/sweep_unlock_params.py --report /tmp/unlock_sweep.md` exits 0, produces a populated sweep table with 20 rows
- `uv run ruff check src tests scripts` → clean
- `uv run pytest -q` → still 101 passing (no infra regression)
- Reports are NOT committed (gitignore `reports/*.md` or leave them out of the commit)

## Out of scope
- Walk-forward (Slice 3)
- Pass/Kill verdict (Slice 3)
- stop_loss optimization
- Unit tests for scripts

## Completion

Execution Report with:
- files changed (3 expected: 2 scripts + maybe `reports/.gitkeep`)
- commit SHAs (2 expected)
- final pytest output (last 3 lines)
- final ruff output
- 5-line excerpt of each report file (portfolio stats line + first row of per-token / sweep table)
- OVERALL PASS/FAIL

Then EXIT.
