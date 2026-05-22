# Fix Phase 0 Review Issues

## Local Review

- Critical: none after fixes.
- Warning: none blocking.
- Info: cache coverage now treats a candle whose open is exactly one interval before the requested completed end boundary as covered.

## Claude Review

Claude review initially requested changes:

- Critical: e2e boundary alignment could make the cached last completed daily candle look one interval short.
- Critical: `_last_completed_candle_end()` looked generic but used epoch-based flooring that is wrong for anchored weekly/monthly intervals.

Fixes applied:

- Changed cache coverage to allow `end_gap <= interval` while keeping the stricter start-side check.
- Added regression coverage for the completed-candle cache boundary.
- Restricted `_last_completed_candle_end()` to fixed intervals and added regression coverage for anchored interval rejection.
- Removed the script's private import of `infra.pipeline._interval_timedelta`.

## Verification

- `uv run pytest -v` -> 80 passed.
- `uv run ruff check src/infra tests/infra scripts` -> clean.
- `uv run python -c "from infra.backtest.engine import _periods_per_year; print(_periods_per_year('1W'), _periods_per_year('1M'), _periods_per_year('1h'))"` -> `52 12 8760`.
- `uv run python -m scripts.run_btc_sma_e2e --days 90` -> `verdict: Sharpe=0.70  MaxDD=-10.01%  n_trades=2`.
- Re-running the same e2e command produced the same verdict.
