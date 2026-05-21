"""End-to-end infrastructure pipeline orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

import duckdb
import pandas as pd

from infra.backtest.engine import BacktestConfig, BacktestResult, run_backtest
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
        candles = _fetch_store_load_candles(config)

    prices = candles["close"]
    entries, exits = signal_fn(prices)
    return run_backtest(prices, entries, exits, config.backtest_config)


def _fetch_store_load_candles(config: PipelineConfig) -> pd.DataFrame:
    client = HyperliquidClient()
    candles = fetch_candles(config.symbol, config.interval, config.start, config.end, client=client)
    write_candles(candles, config.symbol, config.interval)
    return read_candles(config.symbol, config.interval, start=config.start, end=config.end)
