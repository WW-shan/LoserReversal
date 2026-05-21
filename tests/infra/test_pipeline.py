"""Tests for the end-to-end infrastructure pipeline."""

from datetime import datetime, timezone
from unittest.mock import call

import pandas as pd

from infra.backtest.engine import BacktestConfig, BacktestResult
from infra.pipeline import PipelineConfig, run_pipeline


def _candles() -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=3, freq="1D", tz="UTC", name="timestamp")
    return pd.DataFrame(
        {
            "open": [100.0, 101.0, 102.0],
            "high": [110.0, 111.0, 112.0],
            "low": [90.0, 91.0, 92.0],
            "close": [105.0, 106.0, 107.0],
            "volume": [1000.0, 1100.0, 1200.0],
        },
        index=index,
    )


def _result(index: pd.DatetimeIndex) -> BacktestResult:
    equity = pd.Series([10_000.0, 10_100.0, 10_200.0], index=index)
    return BacktestResult(portfolio=object(), stats={"sharpe": 1.0}, equity=equity)


def _signals(prices: pd.Series) -> tuple[pd.Series, pd.Series]:
    return pd.Series(False, index=prices.index), pd.Series(False, index=prices.index)


def test_run_pipeline_uses_cached_candles_without_fetching(mocker):
    candles = _candles()
    expected = _result(candles.index)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 3, tzinfo=timezone.utc)
    backtest_config = BacktestConfig(init_cash=20_000)
    config = PipelineConfig(
        symbol="BTC",
        interval="1d",
        start=start,
        end=end,
        backtest_config=backtest_config,
    )
    read_candles = mocker.patch("infra.pipeline.read_candles", return_value=candles)
    fetch_candles = mocker.patch("infra.pipeline.fetch_candles")
    write_candles = mocker.patch("infra.pipeline.write_candles")
    run_backtest = mocker.patch("infra.pipeline.run_backtest", return_value=expected)

    actual = run_pipeline(config, _signals)

    assert actual is expected
    read_candles.assert_called_once_with("BTC", "1d", start=start, end=end)
    fetch_candles.assert_not_called()
    write_candles.assert_not_called()
    run_backtest.assert_called_once()
    args = run_backtest.call_args.args
    pd.testing.assert_series_equal(args[0], candles["close"])
    assert args[3] is backtest_config


def test_run_pipeline_fetches_stores_and_loads_when_cache_missing(mocker):
    fetched = _candles()
    loaded = fetched.copy()
    expected = _result(loaded.index)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 3, tzinfo=timezone.utc)
    config = PipelineConfig(symbol="ETH", interval="1h", start=start, end=end)
    client = object()
    mocker.patch("infra.pipeline.HyperliquidClient", return_value=client)
    read_candles = mocker.patch(
        "infra.pipeline.read_candles",
        side_effect=[FileNotFoundError("missing cache"), loaded],
    )
    fetch_candles = mocker.patch("infra.pipeline.fetch_candles", return_value=fetched)
    write_candles = mocker.patch("infra.pipeline.write_candles")
    run_backtest = mocker.patch("infra.pipeline.run_backtest", return_value=expected)

    actual = run_pipeline(config, _signals)

    assert actual is expected
    assert read_candles.call_args_list == [
        call("ETH", "1h", start=start, end=end),
        call("ETH", "1h", start=start, end=end),
    ]
    fetch_candles.assert_called_once_with("ETH", "1h", start, end, client=client)
    write_candles.assert_called_once_with(fetched, "ETH", "1h")
    pd.testing.assert_series_equal(run_backtest.call_args.args[0], loaded["close"])


def test_run_pipeline_refreshes_cache_when_use_cache_is_false(mocker):
    fetched = _candles()
    loaded = fetched.copy()
    expected = _result(loaded.index)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 3, tzinfo=timezone.utc)
    config = PipelineConfig(
        symbol="SOL",
        interval="1d",
        start=start,
        end=end,
        use_cache=False,
    )
    client = object()
    mocker.patch("infra.pipeline.HyperliquidClient", return_value=client)
    read_candles = mocker.patch("infra.pipeline.read_candles", return_value=loaded)
    fetch_candles = mocker.patch("infra.pipeline.fetch_candles", return_value=fetched)
    write_candles = mocker.patch("infra.pipeline.write_candles")
    mocker.patch("infra.pipeline.run_backtest", return_value=expected)

    actual = run_pipeline(config, _signals)

    assert actual is expected
    fetch_candles.assert_called_once_with("SOL", "1d", start, end, client=client)
    write_candles.assert_called_once_with(fetched, "SOL", "1d")
    read_candles.assert_called_once_with("SOL", "1d", start=start, end=end)


def test_run_pipeline_refreshes_cache_when_cached_range_is_incomplete(mocker):
    cached = _candles().iloc[1:]
    loaded = _candles()
    expected = _result(loaded.index)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 3, tzinfo=timezone.utc)
    config = PipelineConfig(symbol="BTC", interval="1d", start=start, end=end)
    client = object()
    mocker.patch("infra.pipeline.HyperliquidClient", return_value=client)
    read_candles = mocker.patch("infra.pipeline.read_candles", side_effect=[cached, loaded])
    fetch_candles = mocker.patch("infra.pipeline.fetch_candles", return_value=loaded)
    write_candles = mocker.patch("infra.pipeline.write_candles")
    mocker.patch("infra.pipeline.run_backtest", return_value=expected)

    actual = run_pipeline(config, _signals)

    assert actual is expected
    assert read_candles.call_args_list == [
        call("BTC", "1d", start=start, end=end),
        call("BTC", "1d", start=start, end=end),
    ]
    fetch_candles.assert_called_once_with("BTC", "1d", start, end, client=client)
    write_candles.assert_called_once_with(loaded, "BTC", "1d")


def test_run_pipeline_passes_signal_outputs_to_backtest(mocker):
    candles = _candles()
    expected = _result(candles.index)
    entries = pd.Series([True, False, False], index=candles.index)
    exits = pd.Series([False, False, True], index=candles.index)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 3, tzinfo=timezone.utc)
    config = PipelineConfig(symbol="BTC", interval="1d", start=start, end=end)
    mocker.patch("infra.pipeline.read_candles", return_value=candles)
    run_backtest = mocker.patch("infra.pipeline.run_backtest", return_value=expected)

    actual = run_pipeline(config, lambda prices: (entries.reindex(prices.index), exits.reindex(prices.index)))

    assert actual is expected
    pd.testing.assert_series_equal(run_backtest.call_args.args[1], entries)
    pd.testing.assert_series_equal(run_backtest.call_args.args[2], exits)
