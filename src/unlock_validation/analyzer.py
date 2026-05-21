"""Statistical analysis: abnormal returns, aggregation, pass/fail."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from unlock_validation.config import ECOSYSTEM_CATEGORIES, PASS_FAIL_THRESHOLDS, WINDOWS


def _price_at(prices: pd.DataFrame, target: datetime) -> float:
    """Pick the last available price at or before `target`."""
    available = prices.loc[prices.index <= pd.Timestamp(target)]
    if available.empty:
        raise ValueError(f"No price available at or before {target}")
    return float(available["price"].iloc[-1])


def compute_abnormal_return(
    token_prices: pd.DataFrame,
    btc_prices: pd.DataFrame,
    event_date: datetime,
    window: tuple[int, int],
) -> float:
    """Compute log-return abnormal return over the window relative to BTC.

    window is (offset_start_days, offset_end_days) — e.g. (-7, 0) means T-7 to T0.
    """
    day_start, day_end = window
    start = event_date + timedelta(days=day_start)
    end = event_date + timedelta(days=day_end)

    token_ret = np.log(_price_at(token_prices, end) / _price_at(token_prices, start))
    btc_ret = np.log(_price_at(btc_prices, end) / _price_at(btc_prices, start))
    return token_ret - btc_ret
