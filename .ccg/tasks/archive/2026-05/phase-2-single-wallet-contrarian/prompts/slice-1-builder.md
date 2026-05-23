ROLE_FILE: /Users/ww/.claude/.ccg/prompts/codex/builder.md

# Phase 2 Slice 1 — Wallet Pool Data Layer

## CRITICAL: Anti-monitor directive
- Do NOT tail/ps/grep for other codex processes. Start writing code IMMEDIATELY.
- Do NOT archive the task this slice. Claude will archive after final verdict.

## Working directory
`/Users/ww/Project/crypto-alpha-portfolio`

Use `uv run` for all execution.

## Goal

Build the data layer for Phase 2: fetch HL leaderboard, persist top anti-alpha wallets to parquet, fetch user fills with pagination, persist per-wallet fills. Slice 2 will use this data for backtesting.

## Data source (already verified via spike)

### `fetch_leaderboard()`
- GET `https://stats-data.hyperliquid.xyz/Mainnet/leaderboard`
- Headers: `accept: */*`, `origin: https://app.hyperliquid.xyz`, `user-agent: Mozilla/5.0`
- Returns JSON `{"leaderboardRows": [...]}` with 30k+ entries
- Each row: `{"ethAddress": "0x...", "accountValue": "...", "windowPerformances": [["day", {pnl, roi, vlm}], ["week", ...], ["month", ...], ["allTime", ...]], "prize": ..., "displayName": ...}`
- Numeric fields are strings; coerce to float

### `fetch_user_fills(address, start, end)`
- POST `/info` body `{"type": "userFillsByTime", "user": "0x...", "startTime": <ms>, "endTime": <ms>}`
- Returns list[dict] of fills with: coin, px, sz, side, time(ms), startPosition, dir, closedPnl, hash, oid, crossed, fee, tid, liquidation, feeToken, twapId
- Single response capped at 2000 fills — paginate by advancing `startTime` to `last_fill.time + 1` until empty or hit `end`
- Reuse `infra.hyperliquid_client.HyperliquidClient` for the POST

## Scope (DO NOT exceed)

Create:
- `src/infra/fetchers/leaderboard.py` — `fetch_leaderboard(client=None) -> pd.DataFrame`
- `src/infra/fetchers/user_fills.py` — `fetch_user_fills(address, start, end, client=None) -> pd.DataFrame`
- `scripts/build_wallet_pool.py` — CLI: build anti-alpha wallet pool parquet
- `tests/infra/test_leaderboard.py` — unit tests
- `tests/infra/test_user_fills.py` — unit tests

Modify:
- `src/infra/storage.py` — add `read_wallets()` / `write_wallets_parquet()` and `read_fills(address)` / `write_fills_parquet(df, address)`
- `pyproject.toml` (if needed for new test sub-dir)

## Specifications

### `fetch_leaderboard(client=None) -> pd.DataFrame`

Returns DataFrame with columns:
- `eth_address: str` (lowercase)
- `account_value: float`
- `display_name: str | None`
- `pnl_day, pnl_week, pnl_month, pnl_alltime: float`
- `vlm_day, vlm_week, vlm_month, vlm_alltime: float`
- `roi_day, roi_week, roi_month, roi_alltime: float`

Index: default int. Sort by `pnl_alltime` ascending (worst first).

`client` argument: optional `HyperliquidClient`-like; default uses new instance with `requests.get` to `stats-data.hyperliquid.xyz`. (Note: this is a different URL from `/info` POST. Extend `HyperliquidClient` minimally OR write a small helper inside leaderboard.py that uses `requests` directly. Keep it simple.)

Use tenacity retry like Phase 0 fetchers.

### `fetch_user_fills(address, start, end, client=None) -> pd.DataFrame`

Args:
- `address: str` — wallet (case-insensitive; normalize lowercase)
- `start: datetime | int` — UTC datetime or unix ms
- `end: datetime | int` — same

Returns DataFrame columns:
- `time` (UTC tz-aware index)
- `coin: str`
- `side: str` ("B" or "A")
- `dir: str` ("Open Long" / "Close Short" / etc.)
- `px: float`, `sz: float`, `start_position: float`
- `closed_pnl: float`, `fee: float`
- `oid: int`, `tid: int`, `hash: str`
- `crossed: bool`, `liquidation: bool` (True if liquidation field is non-null)

Pagination:
- Initial request `startTime=start_ms, endTime=end_ms`
- If response len < 2000: done
- Else: get last fill `time`; next request `startTime=last_time + 1, endTime=end_ms`
- Hard cap: 50 paginated requests (safety; warn if hit)
- Dedupe by `tid` across pages (just in case)

### `scripts/build_wallet_pool.py`

CLI:
- `--min-loss FLOAT` (default `-10000.0` — must have lost at least $10k allTime)
- `--min-volume FLOAT` (default `500000.0` — at least $500k volume allTime, filters trivial wallets)
- `--top-n INT` (default 500 — top by allTime volume)
- `--out PATH` (default `data/parquet/anti_alpha_wallets.parquet`)
- `--limit INT | None` (optional — fetch entire leaderboard, then truncate)

Workflow:
1. Call `fetch_leaderboard()`
2. Filter: `pnl_alltime <= min_loss` AND `vlm_alltime >= min_volume` AND `(account_value > 0 OR vlm_alltime >= 10_000_000)`
3. Sort by `vlm_alltime` descending, take top `top_n`
4. Write to parquet via `write_wallets_parquet`
5. Print summary: total fetched, filtered count, sample (top 5 by PnL ascending = worst losers)

Wallet parquet schema (use pyarrow):
- `eth_address: string`, `account_value: float64`, `pnl_alltime: float64`, `vlm_alltime: float64`,
  `roi_alltime: float64`, `display_name: string`, `pnl_month: float64`, `vlm_month: float64`,
  `added_at: timestamp[us, UTC]`

### `storage.py` additions

```python
WALLET_COLUMNS = [
    "eth_address", "account_value", "pnl_alltime", "vlm_alltime",
    "roi_alltime", "display_name", "pnl_month", "vlm_month", "added_at",
]

def write_wallets_parquet(df: pd.DataFrame, path: Path | None = None) -> Path: ...
def read_wallets(path: Path | None = None, min_pnl_loss: float | None = None) -> pd.DataFrame: ...

FILL_COLUMNS = [
    "time", "coin", "side", "dir", "px", "sz", "start_position",
    "closed_pnl", "fee", "oid", "tid", "hash", "crossed", "liquidation",
]

def write_fills_parquet(df: pd.DataFrame, address: str, path: Path | None = None) -> Path:
    # default path: data/parquet/fills/{address.lower()}.parquet
    ...

def read_fills(address: str, start=None, end=None, path: Path | None = None) -> pd.DataFrame: ...
```

## Test cases

### `tests/infra/test_leaderboard.py` (use mocker like Phase 0 test_candles.py)
1. Mocked GET returns 3-row sample → DataFrame has expected columns
2. Coercion: pnl/vlm/roi strings → float64
3. Numeric infinity/NaN strings → safely 0.0 or NaN handled
4. Empty list → empty DataFrame with columns

### `tests/infra/test_user_fills.py`
1. Single-page (< 2000 fills) → all rows returned, no pagination call
2. Multi-page (mocked 2000 then 500 then 0) → 2500 rows returned
3. Dedup on `tid` across pages → no duplicates
4. Address case-insensitive → lowercased in result
5. liquidation field present → `liquidation` col True; null → False
6. Pagination hard cap (50) → warn + return whatever got
7. UTC tz-aware time index
8. `closed_pnl` / `fee` parsed as float64

## Workflow (strict TDD)

For each module:
1. Test first → confirm RED → `git commit -m "test(infra): leaderboard fetcher cases"` (or fills/storage/script)
2. Implement → confirm GREEN + ruff clean → `git commit -m "feat(infra): leaderboard fetcher with retry"` (or similar)

Expected commits (~7-9):
1. test(infra): leaderboard fetcher cases
2. feat(infra): leaderboard fetcher
3. test(infra): user_fills fetcher + pagination cases
4. feat(infra): user_fills paginated fetcher
5. test(infra): wallets + fills storage cases
6. feat(infra): wallets + fills parquet storage
7. feat(scripts): build_wallet_pool CLI
8. (optional) chore: pyproject test-dir update

## Acceptance

- Real `uv run python scripts/build_wallet_pool.py` exits 0
  - Fetches 30k+ wallets
  - Writes ≥ 200 (≤ 500) filtered wallets to `data/parquet/anti_alpha_wallets.parquet`
  - Print top 5 worst-PnL examples
- `uv run pytest -q` → 102+ tests passing (currently 109, expect ~125 after Slice 1)
- `uv run ruff check src tests scripts` clean
- Wallet parquet readable by `read_wallets()`

## Out of scope

- Per-wallet fills batch fetcher (Slice 2 will do this for the 500 wallets)
- Reverse signal computation (Slice 2)
- Cluster detection (Slice 3)
- Walk-forward (Slice 3)

## Completion

Execution Report with:
- files changed
- commit SHAs
- final pytest output (last 3 lines)
- final ruff output
- `scripts/build_wallet_pool.py` real run summary (total leaderboard, filtered count, top-5 sample)

Then EXIT. Do NOT archive.
