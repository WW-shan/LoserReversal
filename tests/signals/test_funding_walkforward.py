from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from signals import funding_walkforward as wf


def test_iter_grid_produces_48_cells():
    cells = list(wf.iter_grid())
    assert len(cells) == 48
    assert {cell.z_threshold for cell in cells} == {1.5, 2.0, 2.5, 3.0}
    assert {cell.hold_hours for cell in cells} == {8, 24, 72, 168}
    assert {cell.lookback_days for cell in cells} == {14, 30, 90}


def test_build_expanding_splits_produces_expected_windows():
    start = pd.Timestamp("2024-01-01T00:00:00Z")
    end = pd.Timestamp("2026-06-01T00:00:00Z")
    splits = wf.build_expanding_splits(start, end, n_splits=3, train_days=180, test_days=90)

    assert len(splits) == 3
    assert splits[0].train_start == start
    assert splits[0].train_end == start + pd.Timedelta(days=180)
    assert splits[0].test_start == splits[0].train_end
    assert splits[0].test_end == splits[0].test_start + pd.Timedelta(days=90)
    # Expanding: train grows by test_days, test stays constant
    assert splits[1].train_end == start + pd.Timedelta(days=180 + 90)
    assert splits[2].train_end == start + pd.Timedelta(days=180 + 180)


def test_build_expanding_splits_truncates_when_history_too_short():
    start = pd.Timestamp("2024-01-01T00:00:00Z")
    end = pd.Timestamp("2024-09-30T00:00:00Z")  # only 9 months, not enough for 3 splits
    splits = wf.build_expanding_splits(start, end, n_splits=5, train_days=180, test_days=90)
    assert 1 <= len(splits) < 5  # truncated


def test_verdict_from_aggregate_green_yellow_red():
    base = {"oos_n_trades": 50}
    assert (
        wf.verdict_from_aggregate({**base, "oos_sharpe": 1.5, "oos_annualized": 0.25})
        == "GREEN"
    )
    assert (
        wf.verdict_from_aggregate({**base, "oos_sharpe": 0.8, "oos_annualized": 0.15})
        == "YELLOW"
    )
    assert (
        wf.verdict_from_aggregate({**base, "oos_sharpe": 0.3, "oos_annualized": 0.20})
        == "RED"
    )
    assert (
        wf.verdict_from_aggregate({**base, "oos_sharpe": 1.5, "oos_annualized": -0.05})
        == "RED"
    )
    # Borderline below GREEN annualized
    assert (
        wf.verdict_from_aggregate({**base, "oos_sharpe": 1.5, "oos_annualized": 0.18})
        == "YELLOW"
    )


def test_verdict_inconclusive_when_n_trades_below_threshold():
    """Phase 1 v1 was misread as RED when it was data_gap. INCONCLUSIVE prevents that."""
    row = {"oos_n_trades": 15, "oos_sharpe": 2.0, "oos_annualized": 0.30}
    assert wf.verdict_from_aggregate(row) == "INCONCLUSIVE"


def test_verdict_from_aggregate_handles_nan_as_red():
    base = {"oos_n_trades": 50}
    assert (
        wf.verdict_from_aggregate({**base, "oos_sharpe": float("nan"), "oos_annualized": 0.2})
        == "RED"
    )
    assert (
        wf.verdict_from_aggregate({**base, "oos_sharpe": 1.5, "oos_annualized": float("nan")})
        == "RED"
    )


def test_select_best_cell_picks_top_sharpe(synthetic_history):
    funding_history, prices = synthetic_history
    cell, sharpe, n_trades = wf.select_best_cell(
        funding_history, prices, min_n_trades=1, taker_fee=0.0, slippage=0.0
    )
    assert cell is not None
    assert math.isfinite(sharpe) or n_trades > 0


def test_select_best_cell_falls_back_when_no_cell_meets_min_trades(empty_history):
    funding_history, prices = empty_history
    cell, sharpe, n_trades = wf.select_best_cell(
        funding_history, prices, min_n_trades=1000, taker_fee=0.0, slippage=0.0
    )
    # No cell meets min_n_trades, fallback returns whichever cell exists
    # n_trades and sharpe degenerate but the call must not crash
    assert isinstance(n_trades, int)


def test_run_walkforward_writes_per_split_and_aggregate_rows(synthetic_history):
    funding_history, prices = synthetic_history
    history_index = list(funding_history.values())[0].index
    history_start = history_index.min()
    history_end = history_index.max()
    splits = wf.build_expanding_splits(
        history_start,
        history_end,
        n_splits=2,
        train_days=120,
        test_days=60,
    )
    assert len(splits) >= 1

    frame = wf.run_walkforward(
        funding_history,
        prices,
        splits,
        min_n_trades=1,
        taker_fee=0.0,
        slippage=0.0,
    )

    assert list(frame.columns) == wf.WALKFORWARD_COLUMNS
    per_split = frame.loc[frame["split_idx"] >= 0]
    aggregate = frame.loc[frame["split_idx"] == -1]
    assert len(per_split) == len(splits)
    assert len(aggregate) == 1
    assert aggregate.iloc[0]["oos_n_trades"] == sum(per_split["oos_n_trades"])


def test_filter_window_slices_funding_and_prices_correctly():
    index = pd.date_range("2024-01-01T00:00:00Z", periods=240, freq="1h", tz="UTC")
    funding = pd.DataFrame({"funding_rate": [0.0001] * 240}, index=index)
    series = pd.Series(range(240), index=index, dtype="float64", name="close")
    funding_history = {"BTC": funding}
    prices = {"BTC": series}

    start = pd.Timestamp("2024-01-02T00:00:00Z")
    end = pd.Timestamp("2024-01-05T00:00:00Z")
    sliced_funding, sliced_prices = wf._filter_window(funding_history, prices, start, end)

    assert sliced_funding["BTC"].index.min() >= start
    assert sliced_funding["BTC"].index.max() < end
    assert sliced_prices["BTC"].index.min() >= start
    assert sliced_prices["BTC"].index.max() < end


@pytest.fixture
def synthetic_history() -> tuple[dict, dict]:
    """Two-token synthetic funding history with periodic positive z spikes.

    Long enough (300 days) to host 2 expanding splits at train=120/test=60.
    """
    hours = 24 * 300
    timestamps = pd.date_range("2024-01-01T00:00:00Z", periods=hours, freq="1h", tz="UTC")
    rates = np.full(hours, 0.0001, dtype="float64")
    # Spike funding every 7 days at hour 0 for 6 hours
    for day in range(7, 300, 14):
        spike_start = day * 24
        for i in range(spike_start, min(spike_start + 6, hours)):
            rates[i] = 0.0015

    base_price = np.linspace(100.0, 130.0, hours, dtype="float64")
    noise = np.sin(np.arange(hours) / 100.0) * 2.0
    close = base_price + noise

    funding = pd.DataFrame(
        {"funding_rate": rates, "premium": np.linspace(0.0, 0.001, hours)},
        index=pd.DatetimeIndex(timestamps, name="timestamp"),
    )
    prices = pd.Series(close, index=timestamps, dtype="float64", name="close")
    return ({"BTC": funding, "ETH": funding.copy()},
            {"BTC": prices, "ETH": prices.copy()})


@pytest.fixture
def empty_history() -> tuple[dict, dict]:
    """Quiet funding (no extreme z) so no cell hits min_trades."""
    hours = 24 * 200
    timestamps = pd.date_range("2024-01-01T00:00:00Z", periods=hours, freq="1h", tz="UTC")
    rates = np.full(hours, 0.0001, dtype="float64")
    funding = pd.DataFrame(
        {"funding_rate": rates, "premium": [0.0] * hours},
        index=pd.DatetimeIndex(timestamps, name="timestamp"),
    )
    close = pd.Series(
        np.linspace(100.0, 110.0, hours), index=timestamps, dtype="float64", name="close"
    )
    return ({"BTC": funding}, {"BTC": close})


def test_select_best_cell_forwards_price_interval(monkeypatch, synthetic_history):
    """select_best_cell must thread price_interval into every BacktestConfig."""
    from signals import funding_walkforward as wf
    from scripts import run_funding_extreme_backtest as backtest

    captured: list[str] = []

    def fake_execute(funding_history, prices, config):
        captured.append(config.price_interval)
        return backtest.SingleConfigResult(
            frame=pd.DataFrame(columns=backtest.OUTPUT_COLUMNS),
            skipped_tokens=[],
        )

    monkeypatch.setattr(wf, "execute_backtest", fake_execute)

    funding_history, prices = synthetic_history
    wf.select_best_cell(
        funding_history,
        prices,
        min_n_trades=1,
        taker_fee=0.0,
        slippage=0.0,
        price_interval="4h",
    )

    assert captured  # at least one cell evaluated
    assert all(value == "4h" for value in captured)


def test_run_oos_forwards_price_interval(monkeypatch, synthetic_history):
    """run_oos passes the price_interval into its single BacktestConfig."""
    from signals import funding_walkforward as wf
    from scripts import run_funding_extreme_backtest as backtest

    captured: dict[str, str] = {}

    def fake_execute(funding_history, prices, config):
        captured["price_interval"] = config.price_interval
        return backtest.SingleConfigResult(
            frame=pd.DataFrame(columns=backtest.OUTPUT_COLUMNS),
            skipped_tokens=[],
        )

    monkeypatch.setattr(wf, "execute_backtest", fake_execute)

    funding_history, prices = synthetic_history
    cell = wf.GridCell(z_threshold=2.0, hold_hours=24, lookback_days=30)
    wf.run_oos(funding_history, prices, cell, taker_fee=0.0, slippage=0.0, price_interval="4h")

    assert captured["price_interval"] == "4h"


def test_run_walkforward_forwards_price_interval(monkeypatch, synthetic_history):
    """run_walkforward must thread price_interval through to BacktestConfig."""
    from signals import funding_walkforward as wf
    from scripts import run_funding_extreme_backtest as backtest

    captured: list[str] = []

    def fake_execute(funding_history, prices, config):
        captured.append(config.price_interval)
        return backtest.SingleConfigResult(
            frame=pd.DataFrame(columns=backtest.OUTPUT_COLUMNS),
            skipped_tokens=[],
        )

    monkeypatch.setattr(wf, "execute_backtest", fake_execute)

    funding_history, prices = synthetic_history
    history_index = list(funding_history.values())[0].index
    splits = wf.build_expanding_splits(
        history_index.min(),
        history_index.max(),
        n_splits=1,
        train_days=120,
        test_days=60,
    )

    wf.run_walkforward(
        funding_history,
        prices,
        splits,
        min_n_trades=1,
        taker_fee=0.0,
        slippage=0.0,
        price_interval="4h",
    )

    assert captured  # IS sweep + OOS evaluation both call execute_backtest
    assert all(value == "4h" for value in captured)
