# Phase 0 — Infrastructure Implementation Plan

> Foundation for all alpha phases. Pure infrastructure, no strategy logic.
> Reuses Phase 1 (`src/unlock_validation/`) as a working example of the conventions.

**Goal**: ship a working pipeline `fetch → store → backtest → report` for any future alpha. After Phase 0, adding a new alpha source (Phase 1/2/3/4) should only mean writing a signal function + a config.

**Architecture**: 4 thin layers, no abstraction beyond what we need:
1. `infra.hyperliquid_client` — single class wrapping HL info/exchange API
2. `infra.fetchers.*` — pure functions, one file per data type (candles, funding, unlocks)
3. `infra.storage` — DuckDB + Parquet, no ORM
4. `infra.backtest` — Vectorbt wrapper + risk primitives (drawdown, sizing)

**Tech additions**:
- `hyperliquid-python-sdk` — HL official SDK
- `duckdb` — analytics DB
- `pyarrow` — Parquet
- `vectorbt` — backtester

---

## Slices (each = one Codex builder run)

### Slice 1: HL client + price/funding fetchers (this run)

**Files**:
- Create `src/infra/__init__.py`
- Create `src/infra/hyperliquid_client.py` — wraps `hyperliquid.info.Info` for read-only queries
- Create `src/infra/fetchers/__init__.py`
- Create `src/infra/fetchers/candles.py` — `fetch_candles(symbol, interval, start, end) -> DataFrame`
- Create `src/infra/fetchers/funding.py` — `fetch_funding(symbol, start, end) -> DataFrame`
- Create `tests/infra/__init__.py`
- Create `tests/infra/test_hyperliquid_client.py` — mock HL API, assert wrapper shape
- Create `tests/infra/test_candles.py` — mock HL response, assert DataFrame schema (index=ts, columns=open/high/low/close/volume)
- Create `tests/infra/test_funding.py` — mock funding response, assert hourly funding rate series
- Modify `pyproject.toml` — add hyperliquid-python-sdk + duckdb + pyarrow + vectorbt to deps

**Acceptance**:
- `uv run pytest tests/infra/` all green (~8-12 tests)
- `uv run python -c "from infra.hyperliquid_client import HyperliquidClient; c = HyperliquidClient(); print(c.universe()[:3])"` returns 3 perp ticker names
- Existing 33 tests still pass

**Conventions** (follow these — they're the Phase 1 conventions):
- TDD: failing test first, then implementation, separate commits
- 100-char line limit, ruff E402/F401 clean
- No comments unless WHY is non-obvious
- DataFrames indexed by UTC datetime (`pd.Timestamp` tz-aware)
- All time params accept `datetime | str` and normalize internally
- Cache to `data/cache/infra/` (different subdir from Phase 1's `data/cache/`)

### Slice 2: storage layer (next run)

DuckDB + Parquet writers + readers for candles / funding / unlocks. Use Phase 1's `data/seed/unlocks_curated.csv` as ground-truth for unlocks Parquet generation.

### Slice 3: backtest scaffold (next run)

Vectorbt wrapper, risk primitives (max drawdown, kelly sizing), backtest config loader. Validate with toy SMA crossover on BTC daily.

### Slice 4: end-to-end integration (next run)

`scripts/run_backtest.py <config.yaml>` — single command runs the full fetch→store→backtest→report pipeline. Used for Phase 1 strategy implementation later.

---

## Out of scope (deferred to per-phase tasks)

- Strategy signal functions — those live in `src/signals/` and are added per-phase
- Live trading wiring (`exchange.order()`) — deferred to Phase 6 paper-trading task
- Multi-exchange via CCXT — only HL for now; add when needed by Phase 3
- Walk-forward optimization framework — added in Phase 1 implementation
