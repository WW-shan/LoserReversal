"""Tests for analyzer: abnormal returns, aggregation, pass/fail."""

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from unlock_validation.analyzer import compute_abnormal_return


def _price_series(values: list[float], start: str = "2025-09-10") -> pd.DataFrame:
    idx = pd.date_range(start, periods=len(values), freq="D", tz="UTC")
    return pd.DataFrame({"price": values}, index=idx)


def test_abnormal_return_zero_when_token_and_btc_move_identically():
    token = _price_series([100, 105])
    btc = _price_series([60000, 63000])  # both +5%
    event_date = datetime(2025, 9, 11, tzinfo=timezone.utc)

    ar = compute_abnormal_return(token, btc, event_date, window=(-1, 0))

    assert ar == pytest.approx(0.0, abs=1e-6)


def test_abnormal_return_positive_when_token_outperforms_btc():
    token = _price_series([100, 110])  # +10%
    btc = _price_series([60000, 63000])  # +5%
    event_date = datetime(2025, 9, 11, tzinfo=timezone.utc)

    ar = compute_abnormal_return(token, btc, event_date, window=(-1, 0))

    # log(1.1) - log(1.05) ≈ 0.0465
    assert ar == pytest.approx(np.log(1.1) - np.log(1.05), abs=1e-6)


def test_abnormal_return_negative_when_token_underperforms_btc():
    token = _price_series([100, 100])  # 0%
    btc = _price_series([60000, 63000])  # +5%
    event_date = datetime(2025, 9, 11, tzinfo=timezone.utc)

    ar = compute_abnormal_return(token, btc, event_date, window=(-1, 0))

    assert ar == pytest.approx(-np.log(1.05), abs=1e-6)


def test_abnormal_return_handles_pre_window():
    token = _price_series([100, 95, 90, 90])  # T-2..T+1, T0 at index 2
    btc = _price_series([60000, 60000, 60000, 60000])
    event_date = datetime(2025, 9, 12, tzinfo=timezone.utc)  # T0

    ar = compute_abnormal_return(token, btc, event_date, window=(-2, 0))

    assert ar < 0
    assert ar == pytest.approx(np.log(90 / 100), abs=1e-6)


from unlock_validation.analyzer import aggregate_statistics


def test_aggregate_statistics_computes_pct_negative():
    events = pd.DataFrame({
        "ar_pre": [-0.05, -0.02, 0.01, -0.10, 0.03],   # 3 negative out of 5
        "ar_day": [0.01, -0.02, 0.0, -0.01, 0.02],
        "ar_post": [-0.03, -0.04, 0.02, -0.01, -0.05], # 4 negative out of 5
        "category": ["team", "investor", "ecosystem", "team", "investor"],
    })

    stats = aggregate_statistics(events)

    assert stats["pct_pre_negative"] == pytest.approx(3 / 5)
    assert stats["pct_post_negative"] == pytest.approx(4 / 5)
    assert stats["n_events"] == 5


def test_aggregate_statistics_computes_mean_pre():
    events = pd.DataFrame({
        "ar_pre": [-0.05, -0.02, 0.01, -0.10, 0.03],
        "ar_day": [0.0, 0.0, 0.0, 0.0, 0.0],
        "ar_post": [0.0, 0.0, 0.0, 0.0, 0.0],
        "category": ["team"] * 5,
    })

    stats = aggregate_statistics(events)

    expected_mean = (-0.05 - 0.02 + 0.01 - 0.10 + 0.03) / 5
    assert stats["mean_pre"] == pytest.approx(expected_mean)


def test_aggregate_statistics_computes_t_test_p_value():
    """With clearly negative AR values, p-value (one-sided AR<0) should be < 0.05."""
    np.random.seed(42)
    events = pd.DataFrame({
        "ar_pre": np.random.normal(loc=-0.05, scale=0.02, size=30),
        "ar_day": np.zeros(30),
        "ar_post": np.zeros(30),
        "category": ["team"] * 30,
    })

    stats = aggregate_statistics(events)

    assert stats["p_value_pre"] < 0.05


def test_aggregate_statistics_empty_events_returns_safe_defaults():
    events = pd.DataFrame(columns=["ar_pre", "ar_day", "ar_post", "category"])

    stats = aggregate_statistics(events)

    assert stats["n_events"] == 0
    assert stats["pct_pre_negative"] is None
    assert stats["mean_pre"] is None
    assert stats["p_value_pre"] is None
