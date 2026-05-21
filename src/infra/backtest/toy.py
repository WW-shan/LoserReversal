"""Toy signal generators for end-to-end backtest validation."""

from __future__ import annotations

import pandas as pd


def sma_crossover_signals(
    prices: pd.Series,
    fast: int = 10,
    slow: int = 30,
) -> tuple[pd.Series, pd.Series]:
    """Return entry and exit signals for an SMA crossover."""
    close = prices.astype("float64")
    fast_sma = close.rolling(fast).mean()
    slow_sma = close.rolling(slow).mean()
    above = fast_sma > slow_sma
    was_above = above.shift(1, fill_value=False)

    entries = (above & ~was_above).astype(bool)
    exits = (~above & was_above).astype(bool)
    return entries, exits
