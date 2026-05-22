"""Tests for vectorbt backtest wrapper."""

import pandas as pd
import pytest

from infra.backtest.engine import BacktestConfig, _periods_per_year, run_backtest


def test_run_backtest_buy_and_hold_tracks_price_return_after_entry_fee():
    prices = pd.Series(
        [100.0, 110.0, 120.0],
        index=pd.date_range("2026-01-01", periods=3, freq="1D", tz="UTC"),
        name="close",
    )
    entries = pd.Series([True, False, False], index=prices.index)
    exits = pd.Series([False, False, False], index=prices.index)
    config = BacktestConfig(init_cash=10_000, fees=0.001, slippage=0.0)

    result = run_backtest(prices, entries, exits, config)

    expected_final = config.init_cash / (1.0 + config.fees) * (prices.iloc[-1] / prices.iloc[0])
    assert result.equity.iloc[-1] == pytest.approx(expected_final)
    assert result.stats["total_return"] == pytest.approx(expected_final / config.init_cash - 1.0)


def test_run_backtest_counts_one_closed_trade():
    prices = pd.Series(
        [100.0, 110.0, 120.0, 115.0],
        index=pd.date_range("2026-01-01", periods=4, freq="1D", tz="UTC"),
        name="close",
    )
    entries = pd.Series([True, False, False, False], index=prices.index)
    exits = pd.Series([False, False, True, False], index=prices.index)

    result = run_backtest(prices, entries, exits, BacktestConfig(fees=0.0, slippage=0.0))

    assert result.stats["n_trades"] == 1
    assert result.stats["win_rate"] == 1.0


def test_run_backtest_no_signals_preserves_initial_cash():
    prices = pd.Series(
        [100.0, 90.0, 110.0],
        index=pd.date_range("2026-01-01", periods=3, freq="1D", tz="UTC"),
        name="close",
    )
    entries = pd.Series(False, index=prices.index)
    exits = pd.Series(False, index=prices.index)
    config = BacktestConfig(init_cash=10_000)

    result = run_backtest(prices, entries, exits, config)

    assert result.equity.tolist() == [config.init_cash, config.init_cash, config.init_cash]
    assert result.stats["total_return"] == 0.0
    assert result.stats["n_trades"] == 0


@pytest.mark.parametrize(
    ("freq", "expected"),
    [
        ("1W", 52),
        ("1M", 12),
        ("1h", 8760),
    ],
)
def test_periods_per_year_uses_lookup_for_supported_frequencies(freq, expected):
    assert _periods_per_year(freq) == expected


@pytest.mark.parametrize(
    ("config_freq", "index_freq"),
    [
        ("1W", "1W"),
        ("1M", "ME"),
        ("1h", "1h"),
    ],
)
def test_run_backtest_accepts_weekly_monthly_and_hourly_frequencies(config_freq, index_freq):
    prices = pd.Series(
        [100.0, 101.0, 102.0, 103.0],
        index=pd.date_range("2026-01-01", periods=4, freq=index_freq, tz="UTC"),
        name="close",
    )
    entries = pd.Series(False, index=prices.index)
    exits = pd.Series(False, index=prices.index)

    result = run_backtest(prices, entries, exits, BacktestConfig(freq=config_freq))

    assert result.stats["n_trades"] == 0
