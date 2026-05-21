# Phase 0 Slice 4 Review

## Local Review

- Critical: none after fixes.
- Warning: none blocking.
- Info: generated artifacts are ignored as intended:
  - `data/parquet/candles/BTC_1d.parquet`
  - `reports/backtest_btc_sma10-30.md`

## Claude Review

Initial Claude review found one Critical issue:

- `src/infra/pipeline.py` trusted any cache hit without validating that cached candles covered the requested range. This could let a prior `--days 30` cache produce a later `--days 90` report over only 30 days.

Fix:

- Added interval-aware cache coverage validation.
- Added regression coverage for incomplete cached ranges.
- Added CLI validation for positive `days`, `fast`, `slow`, `fast < slow`, and path-safe symbols.

Claude re-review result:

- Previous Critical: resolved.
- Critical: none.
- Warning/Info: boundary/refinement suggestions only; re-review approved Slice 4 delivery.

## Verification

- `uv run pytest -v` -> 67 passed.
- `uv run ruff check src/infra tests/infra scripts` -> clean.
- `uv run python -m scripts.run_btc_sma_e2e --days 90` -> exit 0, printed Sharpe/MaxDD/n_trades/report path.
- `reports/backtest_btc_sma10-30.md` contains the stats table.
- `data/parquet/candles/BTC_1d.parquet` exists.
