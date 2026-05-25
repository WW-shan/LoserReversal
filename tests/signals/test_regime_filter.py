from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from signals import regime_filter as rf


def test_compute_btc_regime_marks_bear_when_close_below_sma():
    # 250 days: first 200 flat at 100 to warm SMA, then drop to 80 (bear)
    days = pd.date_range("2024-01-01T00:00:00Z", periods=250, freq="1D", tz="UTC")
    closes = np.full(250, 100.0)
    closes[200:] = 80.0
    series = pd.Series(closes, index=days, dtype="float64", name="close")

    bear = rf.compute_btc_regime(series, window=200)

    assert bear.iloc[:199].isna().all()  # not enough history yet
    assert bear.iloc[199] in {True, False, pd.NA}
    assert bool(bear.iloc[210]) is True   # below SMA after drop
    assert bool(bear.iloc[200]) is True   # right at the drop


def test_compute_btc_regime_marks_bull_when_close_above_sma():
    days = pd.date_range("2024-01-01T00:00:00Z", periods=250, freq="1D", tz="UTC")
    closes = np.full(250, 100.0)
    closes[200:] = 120.0
    series = pd.Series(closes, index=days, dtype="float64", name="close")

    bear = rf.compute_btc_regime(series, window=200)

    assert bool(bear.iloc[210]) is False  # above SMA after rise


def test_compute_btc_regime_handles_hourly_input_via_daily_resample():
    hours = pd.date_range("2024-01-01T00:00:00Z", periods=250 * 24, freq="1h", tz="UTC")
    closes = np.full(len(hours), 100.0)
    closes[200 * 24 :] = 80.0
    series = pd.Series(closes, index=hours, dtype="float64", name="close")

    bear = rf.compute_btc_regime(series, window=200)

    # Daily output even though input is hourly
    diffs = bear.index.to_series().diff().dropna().unique()
    assert all(diff == pd.Timedelta(days=1) for diff in diffs)
    assert bool(bear.iloc[210]) is True


def test_compute_btc_regime_returns_empty_for_empty_input():
    empty = pd.Series(dtype="float64")
    bear = rf.compute_btc_regime(empty, window=200)
    assert bear.empty


def test_compute_btc_regime_rejects_invalid_window():
    days = pd.date_range("2024-01-01T00:00:00Z", periods=10, freq="1D", tz="UTC")
    series = pd.Series(np.arange(10), index=days, dtype="float64")
    with pytest.raises(ValueError):
        rf.compute_btc_regime(series, window=0)


def test_is_bear_at_returns_last_known_bear_flag_before_target():
    days = pd.date_range("2024-01-01T00:00:00Z", periods=5, freq="1D", tz="UTC")
    bear = pd.Series([pd.NA, True, True, False, False], index=days, dtype="boolean", name="bear")

    assert rf.is_bear_at(bear, pd.Timestamp("2024-01-03T12:00:00Z")) is True
    assert rf.is_bear_at(bear, pd.Timestamp("2024-01-05T00:00:00Z")) is False


def test_is_bear_at_returns_none_when_no_warmup_yet():
    days = pd.date_range("2024-01-01T00:00:00Z", periods=3, freq="1D", tz="UTC")
    bear = pd.Series([pd.NA, pd.NA, pd.NA], index=days, dtype="boolean", name="bear")

    assert rf.is_bear_at(bear, pd.Timestamp("2024-01-02T00:00:00Z")) is None


def test_filter_events_by_regime_keeps_only_bear_period_shorts():
    days = pd.date_range("2024-01-01T00:00:00Z", periods=10, freq="1D", tz="UTC")
    bear = pd.Series(
        [True, True, True, False, False, False, True, True, False, False],
        index=days, dtype="boolean", name="bear",
    )
    events = pd.DataFrame({
        "token": ["A", "B", "C", "D"],
        "unlock_date": pd.to_datetime(
            ["2024-01-02", "2024-01-05", "2024-01-07", "2024-01-10"], utc=True
        ),
    })

    filtered = rf.filter_events_by_regime(events, bear, direction="short")
    assert set(filtered["token"]) == {"A", "C"}  # B and D landed in bull


def test_filter_events_by_regime_keeps_only_bull_period_longs():
    days = pd.date_range("2024-01-01T00:00:00Z", periods=10, freq="1D", tz="UTC")
    bear = pd.Series(
        [True, True, False, False, True, True, False, False, False, True],
        index=days, dtype="boolean", name="bear",
    )
    events = pd.DataFrame({
        "token": ["A", "B", "C", "D"],
        "unlock_date": pd.to_datetime(
            ["2024-01-02", "2024-01-04", "2024-01-08", "2024-01-10"], utc=True
        ),
    })

    filtered = rf.filter_events_by_regime(events, bear, direction="long")
    assert set(filtered["token"]) == {"B", "C"}


def test_filter_events_by_regime_both_returns_unchanged():
    events = pd.DataFrame({
        "token": ["A"],
        "unlock_date": pd.to_datetime(["2024-01-02"], utc=True),
    })
    bear = pd.Series([True], index=pd.date_range("2024-01-01", periods=1, freq="1D", tz="UTC"))
    out = rf.filter_events_by_regime(events, bear, direction="both")
    assert len(out) == 1


def test_filter_events_by_regime_drops_unknown_unless_pass_through():
    """Events before SMA warmup get dropped by default."""
    days = pd.date_range("2024-01-01T00:00:00Z", periods=3, freq="1D", tz="UTC")
    bear = pd.Series([pd.NA, pd.NA, True], index=days, dtype="boolean", name="bear")
    events = pd.DataFrame({
        "token": ["A", "B"],
        "unlock_date": pd.to_datetime(["2024-01-01", "2024-01-03"], utc=True),
    })

    default = rf.filter_events_by_regime(events, bear, direction="short")
    assert set(default["token"]) == {"B"}  # A dropped, no regime

    pass_through = rf.filter_events_by_regime(
        events, bear, direction="short", pass_through_when_unknown=True
    )
    assert set(pass_through["token"]) == {"A", "B"}


def test_filter_events_by_regime_rejects_invalid_direction():
    events = pd.DataFrame({"token": ["A"], "unlock_date": pd.to_datetime(["2024-01-01"], utc=True)})
    bear = pd.Series([True], index=pd.date_range("2024-01-01", periods=1, freq="1D", tz="UTC"))
    with pytest.raises(ValueError):
        rf.filter_events_by_regime(events, bear, direction="sideways")
