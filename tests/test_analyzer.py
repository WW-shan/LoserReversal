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
