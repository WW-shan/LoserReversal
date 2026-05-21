"""Statistical analysis: abnormal returns, aggregation, pass/fail."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

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


def aggregate_statistics(events: pd.DataFrame) -> dict:
    """Compute the five summary metrics over a set of events with AR columns.

    Returned dict shape:
      n_events, pct_pre_negative, pct_post_negative, mean_pre, mean_post, p_value_pre
    """
    if len(events) == 0:
        return {
            "n_events": 0,
            "pct_pre_negative": None,
            "pct_post_negative": None,
            "mean_pre": None,
            "mean_post": None,
            "p_value_pre": None,
        }

    ar_pre = events["ar_pre"].to_numpy()
    ar_post = events["ar_post"].to_numpy()

    # One-sided t-test: H0 mean=0, H1 mean<0
    t_stat, p_two_sided = scipy_stats.ttest_1samp(ar_pre, popmean=0.0)
    p_one_sided = p_two_sided / 2 if t_stat < 0 else 1 - p_two_sided / 2

    return {
        "n_events": len(events),
        "pct_pre_negative": float((ar_pre < 0).mean()),
        "pct_post_negative": float((ar_post < 0).mean()),
        "mean_pre": float(ar_pre.mean()),
        "mean_post": float(ar_post.mean()),
        "p_value_pre": float(p_one_sided),
    }
