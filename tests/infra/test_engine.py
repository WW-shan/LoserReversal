"""Tests for vectorbt backtest wrapper."""

import pandas as pd
import pytest

from datetime import datetime, timezone

from infra.backtest.engine import BacktestConfig, periods_per_year, run_backtest
from infra.pipeline import PipelineConfig, candles_cover_range
from scripts.run_btc_sma_e2e import _last_completed_candle_end


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
def test_period_lookup_uses_supported_frequencies(freq, expected):
    assert periods_per_year(freq) == expected


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


@pytest.mark.parametrize(
    ("interval", "now", "expected"),
    [
        (
            "1d",
            datetime(2026, 5, 22, 15, 30, tzinfo=timezone.utc),
            datetime(2026, 5, 22, 0, 0, tzinfo=timezone.utc),
        ),
        (
            "1h",
            datetime(2026, 5, 22, 15, 30, 45, tzinfo=timezone.utc),
            datetime(2026, 5, 22, 15, 0, tzinfo=timezone.utc),
        ),
        (
            "5m",
            datetime(2026, 5, 22, 15, 32, 1, tzinfo=timezone.utc),
            datetime(2026, 5, 22, 15, 30, tzinfo=timezone.utc),
        ),
    ],
)
def test_last_completed_candle_end_aligns_to_previous_boundary(interval, now, expected):
    assert _last_completed_candle_end(interval, now) == expected


def test_last_completed_candle_end_rejects_anchored_intervals():
    with pytest.raises(ValueError, match="fixed interval"):
        _last_completed_candle_end("1w", datetime(2026, 5, 22, 15, 30, tzinfo=timezone.utc))


def test_candle_range_cover_accepts_last_open_at_completed_end_boundary():
    candles = pd.DataFrame(
        {"close": [100.0]},
        index=pd.DatetimeIndex([pd.Timestamp("2026-05-21T00:00:00Z")], name="timestamp"),
    )
    config = PipelineConfig(
        symbol="BTC",
        interval="1d",
        start=datetime(2026, 5, 21, tzinfo=timezone.utc),
        end=datetime(2026, 5, 22, tzinfo=timezone.utc),
    )

    assert candles_cover_range(candles, config)


def test_run_backtest_applies_stop_loss_caps_trade_loss():
    """A short trade where price rises >10% must exit by the stop loss path.

    Phase 1.5 Ablation D: per-trade -10% stop. We compare the no-stop short
    (price climbs through entry, equity bleeds) against sl_stop=0.10 (engine
    closes the position once the running price exceeds entry x 1.10).
    """
    prices = pd.Series(
        [100.0, 105.0, 112.0, 118.0, 125.0],
        index=pd.date_range("2026-01-01", periods=5, freq="1D", tz="UTC"),
        name="close",
    )
    entries = pd.Series([True, False, False, False, False], index=prices.index)
    exits = pd.Series(False, index=prices.index)
    base_config = BacktestConfig(
        init_cash=10_000.0,
        fees=0.0,
        slippage=0.0,
        direction="shortonly",
    )
    stop_config = BacktestConfig(
        init_cash=10_000.0,
        fees=0.0,
        slippage=0.0,
        direction="shortonly",
        stop_loss=0.10,
    )

    baseline = run_backtest(prices, entries, exits, base_config)
    stopped = run_backtest(prices, entries, exits, stop_config)

    # Baseline short held through full rally: loss ~ -25% on equity.
    assert baseline.equity.iloc[-1] < 8_000.0
    # Stop loss exits the trade after price first closes above entry*1.10,
    # so final equity must be strictly larger than the unstopped run.
    assert stopped.equity.iloc[-1] > baseline.equity.iloc[-1]
    # And the stopped trade should be marked as closed with one realised trade.
    assert stopped.stats["n_trades"] == 1


def test_run_backtest_no_stop_loss_passes_through_unchanged():
    """With stop_loss=None, engine output must match the pre-Ablation-D path."""
    prices = pd.Series(
        [100.0, 105.0, 112.0, 118.0, 125.0],
        index=pd.date_range("2026-01-01", periods=5, freq="1D", tz="UTC"),
        name="close",
    )
    entries = pd.Series([True, False, False, False, False], index=prices.index)
    exits = pd.Series(False, index=prices.index)
    legacy_config = BacktestConfig(
        init_cash=10_000.0,
        fees=0.0,
        slippage=0.0,
        direction="shortonly",
    )
    explicit_none = BacktestConfig(
        init_cash=10_000.0,
        fees=0.0,
        slippage=0.0,
        direction="shortonly",
        stop_loss=None,
    )

    legacy = run_backtest(prices, entries, exits, legacy_config)
    explicit = run_backtest(prices, entries, exits, explicit_none)

    assert legacy.equity.tolist() == explicit.equity.tolist()
    assert legacy.stats["n_trades"] == explicit.stats["n_trades"]
    assert legacy.stats["total_return"] == pytest.approx(explicit.stats["total_return"])
