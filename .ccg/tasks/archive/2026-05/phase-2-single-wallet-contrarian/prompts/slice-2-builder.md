ROLE_FILE: /Users/ww/.claude/.ccg/prompts/codex/builder.md

# Phase 2 Slice 2 — Reverse Backtest + Holding-Time Sweep

## CRITICAL: Anti-monitor directive
- Do NOT tail/ps/grep. Start IMMEDIATELY.
- Do NOT archive — Claude will after final LGTM.

## Working directory
`/Users/ww/Project/crypto-alpha-portfolio`

Use `uv run`.

## Goal

Build reverse-follow backtest infrastructure. Read wallet pool from Slice 1, batch-fetch their fills, generate reverse signals, run backtest per wallet, sweep over holding time.

**Expected:** This is data-heavy. Plan for sample-first (50 wallets) then optionally scale up. Aim for <60 min total execution.

## Scope (DO NOT exceed)

Create:
- `src/signals/wallet_reverse_v1.py` — `reverse_signal(fills_df, holding_hours)` → per-coin (entries, exits) DataFrame
- `scripts/fetch_pool_fills.py` — batch fetch fills for all wallets in pool, cache to parquet
- `scripts/run_wallet_reverse_backtest.py` — single-config e2e
- `scripts/sweep_wallet_holding.py` — sweep holding ∈ {1h, 4h, 12h, 24h}
- `tests/signals/test_wallet_reverse_v1.py` — unit tests on signal logic
- `tests/scripts/test_fetch_pool_fills.py` — unit test on batch fetch

Modify:
- `src/infra/storage.py` if helpers need extension (read_fills already exists from Slice 1)
- `data/parquet/fills/{addr}.parquet` — output of fetch_pool_fills

## Architectural decisions (use these, do NOT redesign)

### `fetch_pool_fills.py`

CLI flags:
- `--top-n INT` (default 50; cap to wallet pool size)
- `--lookback-days INT` (default 180)
- `--throttle-ms INT` (default 200 — per-wallet sleep to be polite)
- `--out-dir PATH` (default `data/parquet/fills/`)
- `--skip-existing BOOL` (default True — skip wallets with cached fills)

Workflow:
1. Read wallet pool via `read_wallets()` — already sorted by vlm desc
2. Take top N
3. For each wallet:
   - If skip_existing AND `fills/{addr}.parquet` exists with rows: skip
   - Else: `fetch_user_fills(addr, now - lookback_days, now)`, then `write_fills_parquet(df, addr)`
4. Progress to stderr: `[3/50] 0xabc... fetched 1532 fills (12.3s, total runtime 145s)`
5. Print summary at end: wallets fetched / skipped / failed / total fills / disk size

### `reverse_signal(fills_df, holding_hours, coin_filter=None) -> dict[coin, (entries, exits)]`

For each row in `fills_df`:
- Skip if `dir not in {"Open Long", "Open Short"}` (only open positions; HL stores Close events separately)
- Skip if `coin_filter` provided and `coin not in coin_filter` (e.g. only HL perp universe)
- Skip if `sz * px < 1000 OR sz * px > 200_000` per ROADMAP retail-size filter
- Reverse direction:
  - `"Open Long"` → SHORT entry at `time`
  - `"Open Short"` → LONG entry at `time`
- Exit `time + holding_hours`

Build `entries / exits` bool Series per coin, indexed by candle timestamp (so signal can drive `run_backtest`).

Returns `dict[coin, tuple[entries, exits, side]]` where side is "long" or "short".

NB: `run_backtest` only handles single-direction signals per call. For reverse strategy, run TWO backtests per coin (one shortonly entries, one longonly entries), then aggregate.

OR — simpler — convert to a single notional position track:
- At each entry timestamp, `+1` if long-reverse / `-1` if short-reverse
- Hold for `holding_hours`, then `0`
- Compute P&L as `position_t * (price_{t+1} - price_t)` and sum

Use whichever is cleaner. The simpler path-tracking approach is preferable for KISS.

### `run_wallet_reverse_backtest.py`

CLI flags:
- `--holding-hours FLOAT` (default 4.0)
- `--top-wallet-n INT` (default 50)
- `--candle-interval STR` (default "1h" — finer than 1d to capture intraday reverse opportunities)
- `--init-cash FLOAT` (default 10000.0 per wallet)
- `--fees FLOAT` (default 0.0005)
- `--slippage FLOAT` (default 0.0002)
- `--report PATH` (default `reports/wallet_reverse_v1_backtest.md`)

Workflow:
1. Read top N wallets
2. For each wallet: `read_fills(addr)` (must exist; if not, log warning skip)
3. For each wallet: `reverse_signal(fills, holding_hours)` → dict[coin, signals]
4. For each (wallet, coin) signal: backtest (need 1h candles for that coin — fetch via existing pipeline if not cached)
5. Aggregate per wallet: Sharpe, MaxDD, n_trades, win_rate, total_return
6. Aggregate across wallets: same equal-weight model as Phase 1 (sum equity, n_backtested_wallets, n_failed_wallets)
7. Write report with same structure as Phase 1: Decision Gate, Funnel (fills → in-size → with-candle → trades), Per-wallet stats, Portfolio stats, Equity curve

### `sweep_wallet_holding.py`

Sweep holding ∈ {1, 4, 12, 24} hours. For each, run `run_wallet_reverse_backtest` and aggregate.

Output `reports/wallet_reverse_v1_sweep.md`:
- table: holding | n_trades | sharpe | sortino | max_dd | total_return | win_rate | eligible (n_trades ≥ 100)
- sort by eligibility desc, sharpe desc
- Decision Gate Summary at top

## Conventions

- `from __future__ import annotations`
- 100-char lines
- argparse with validation
- UTC tz-aware datetimes
- No emoji
- Use existing `infra.backtest.{engine,risk}` helpers
- Same builder/reviewer flow lessons from Phase 1: do NOT archive after this slice

## Workflow

~8-10 commits expected. TDD where it makes sense (signal logic + storage). For scripts use real-run validation.

1. `test(signals): wallet_reverse_v1 signal cases`
2. `feat(signals): wallet_reverse_v1 reverse signal generator`
3. `test(scripts): fetch_pool_fills batch logic`
4. `feat(scripts): fetch_pool_fills CLI`
5. `feat(scripts): wallet reverse backtest e2e runner`
6. `feat(scripts): wallet holding-time sweep`
7. (optional) `chore(reports): seed wallet_reverse reports`

## Acceptance

- `uv run python scripts/fetch_pool_fills.py --top-n 50 --lookback-days 90` exits 0
  - Note: real fetch — may take 10-30 min. If exceeds 60 min, stop and consider `--top-n 30` or `--lookback-days 60`
  - Output: `data/parquet/fills/{addr}.parquet` for each fetched wallet
- `uv run python scripts/run_wallet_reverse_backtest.py --top-wallet-n 50` exits 0
  - Produces a populated report at `reports/wallet_reverse_v1_backtest.md`
- `uv run python scripts/sweep_wallet_holding.py --top-wallet-n 50` exits 0
  - Sweep report with 4 rows (1h/4h/12h/24h)
- `uv run pytest -q` → 133 + new tests pass
- `uv run ruff check src tests scripts` clean

## Test cases (unit)

`tests/signals/test_wallet_reverse_v1.py` (6+):
1. `Open Long` fill → SHORT reverse entry
2. `Open Short` fill → LONG reverse entry
3. `Close Long` / `Close Short` fill → ignored
4. Fill below retail size ($1k) → ignored
5. Fill above whale size ($200k) → ignored
6. Holding time correctly converts to exit timestamp
7. Multiple fills same coin → multiple entry/exit pairs

`tests/scripts/test_fetch_pool_fills.py` (3+):
1. skip_existing=True with existing parquet → does NOT fetch
2. skip_existing=False → always fetches
3. Failed fetch (HTTP error) → logs warning, continues to next wallet

## Out of scope

- Cluster signal (Slice 3)
- Walk-forward (Slice 3)
- Pass/Kill verdict (Slice 3)

## Completion

Execution Report with:
- files changed, commit SHAs
- final pytest output, ruff output
- `fetch_pool_fills.py` runtime summary (wallets fetched, fills total, time)
- `run_wallet_reverse_backtest.py` portfolio Sharpe + n_trades
- `sweep_wallet_holding.py` best holding by Sharpe + n_trades
- Decision Gate verdict (informal, not final) — e.g. "trade count likely sufficient for cluster slice"

Then EXIT.
