"""Tests for toy SMA crossover signals."""

import pandas as pd

from infra.backtest.toy import sma_crossover_signals


def test_sma_crossover_signals_enter_once_on_monotonic_uptrend():
    prices = pd.Series(
        range(1, 21),
        index=pd.date_range("2026-01-01", periods=20, freq="1D", tz="UTC"),
        dtype="float64",
    )

    entries, exits = sma_crossover_signals(prices, fast=3, slow=5)

    assert entries.sum() == 1
    assert entries.index.equals(prices.index)
    assert exits.sum() == 0


def test_sma_crossover_signals_do_not_enter_on_monotonic_downtrend():
    prices = pd.Series(
        range(20, 0, -1),
        index=pd.date_range("2026-01-01", periods=20, freq="1D", tz="UTC"),
        dtype="float64",
    )

    entries, exits = sma_crossover_signals(prices, fast=3, slow=5)

    assert entries.sum() == 0
    assert exits.sum() == 0


def test_sma_crossover_signals_exit_on_reverse_cross():
    prices = pd.Series(
        [10, 11, 12, 13, 14, 13, 12, 11, 10, 9],
        index=pd.date_range("2026-01-01", periods=10, freq="1D", tz="UTC"),
        dtype="float64",
    )

    entries, exits = sma_crossover_signals(prices, fast=2, slow=4)

    assert entries.sum() == 1
    assert exits.sum() == 1
    assert exits.idxmax() > entries.idxmax()
