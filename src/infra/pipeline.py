"""End-to-end infrastructure pipeline orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

import duckdb
import pandas as pd

from infra.backtest.engine import INTERVAL_TABLE, BacktestConfig, BacktestResult, run_backtest
from infra.fetchers.candles import fetch_candles
from infra.hyperliquid_client import HyperliquidClient
from infra.storage import read_candles, write_candles


@dataclass
class PipelineConfig:
    symbol: str
    interval: str
    start: datetime
    end: datetime
    use_cache: bool = True
    backtest_config: BacktestConfig | None = None


SignalFn = Callable[[pd.Series], tuple[pd.Series, pd.Series]]


def run_pipeline(
    config: PipelineConfig,
    signal_fn: SignalFn,
) -> BacktestResult:
    """Run fetch, Parquet cache, DuckDB load, signal generation, and backtest."""
    if config.use_cache:
        try:
            candles = read_candles(config.symbol, config.interval, start=config.start, end=config.end)
        except (FileNotFoundError, OSError, duckdb.IOException):
            candles = _fetch_store_load_candles(config)
        else:
            if not _candles_cover_range(candles, config):
                candles = _fetch_store_load_candles(config)
    else:
        candles = _fetch_store_load_candles(config)

    prices = candles["close"]
    entries, exits = signal_fn(prices)
    return run_backtest(prices, entries, exits, config.backtest_config)


def _fetch_store_load_candles(config: PipelineConfig) -> pd.DataFrame:
    client = HyperliquidClient()
    candles = fetch_candles(config.symbol, config.interval, config.start, config.end, client=client)
    write_candles(candles, config.symbol, config.interval)
    return read_candles(config.symbol, config.interval, start=config.start, end=config.end)


def _candles_cover_range(candles: pd.DataFrame, config: PipelineConfig) -> bool:
    if candles.empty:
        return False

    interval = _interval_timedelta(config.interval)
    start = _coerce_utc_timestamp(config.start)
    end = _coerce_utc_timestamp(config.end)
    first = _coerce_utc_timestamp(candles.index.min())
    last = _coerce_utc_timestamp(candles.index.max())

    start_gap = first - start if first > start else pd.Timedelta(0)
    end_gap = end - last if last < end else pd.Timedelta(0)
    return start_gap < interval and end_gap < interval


def _coerce_utc_timestamp(value: datetime | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tz is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _interval_timedelta(interval: str) -> pd.Timedelta:
    if interval in INTERVAL_TABLE:
        return INTERVAL_TABLE[interval][1]

    try:
        return pd.Timedelta(interval)
    except ValueError as error:
        raise ValueError(f"Unsupported candle interval: {interval}") from error
