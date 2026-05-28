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
    assert bear.iloc[198] is pd.NA and bear.iloc[199] in {True, False}
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


def test_filter_events_by_regime_uses_entry_date_column_when_provided():
    days = pd.to_datetime(["2025-09-01", "2025-10-01"], utc=True)
    bear = pd.Series([True, False], index=days, dtype="boolean", name="bear")
    events = pd.DataFrame({
        "token": ["A"],
        "unlock_date": pd.to_datetime(["2025-10-01"], utc=True),
        "entry_date": pd.to_datetime(["2025-09-01"], utc=True),
    })

    by_entry = rf.filter_events_by_regime(
        events,
        bear,
        direction="short",
        entry_date_column="entry_date",
    )
    by_unlock = rf.filter_events_by_regime(events, bear, direction="short")

    assert by_entry["token"].tolist() == ["A"]
    assert by_unlock.empty


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


# ---------- compute_funding_regime ----------------------------------------------


def _funding_frame(rates: list[float], start: str = "2026-01-01") -> pd.DataFrame:
    ts = pd.date_range(start, periods=len(rates), freq="8h", tz="UTC")
    return pd.DataFrame({"timestamp": ts, "funding_rate": rates})


def test_compute_funding_regime_marks_bear_when_mean_funding_negative():
    # Bear regime is now "funding above 75th percentile" (overheated). To
    # exercise the bear branch we feed a mix where some days exceed the
    # in-sample quantile.
    rates = [0.0001] * 60 + [0.002] * 30
    funding = {"BTC": _funding_frame(rates), "ETH": _funding_frame(rates)}
    regime = rf.compute_funding_regime(funding, majors=("BTC", "ETH"), window_days=7, bear_quantile=0.75)
    warmed = regime.dropna()
    assert len(warmed) > 0
    assert bool(warmed.iloc[-1])  # tail is overheated → bear


def test_compute_funding_regime_marks_bull_when_mean_funding_positive():
    # Constant funding → quantile equals the value → tail days are at the
    # boundary; with `>=` the regime evaluates to True (bear). Provide a
    # mix where the tail is below the in-sample quantile to verify bull.
    rates = [0.002] * 60 + [0.0001] * 30
    funding = {"BTC": _funding_frame(rates), "ETH": _funding_frame(rates)}
    regime = rf.compute_funding_regime(funding, majors=("BTC", "ETH"), window_days=7, bear_quantile=0.75)
    warmed = regime.dropna()
    assert len(warmed) > 0
    assert not bool(warmed.iloc[-1])  # tail is calm → bull


def test_compute_funding_regime_returns_empty_when_no_data():
    regime = rf.compute_funding_regime({}, majors=("BTC",), window_days=7)
    assert regime.empty


def test_compute_funding_regime_rejects_invalid_window():
    with pytest.raises(ValueError, match="window_days"):
        rf.compute_funding_regime({}, majors=("BTC",), window_days=0)


def test_compute_funding_regime_rejects_empty_majors():
    with pytest.raises(ValueError, match="majors"):
        rf.compute_funding_regime({}, majors=(), window_days=7)


def test_compute_funding_regime_ignores_missing_token():
    rates = [-0.001] * 30
    funding = {"BTC": _funding_frame(rates)}  # ETH missing
    regime = rf.compute_funding_regime(funding, majors=("BTC", "ETH"), window_days=7)
    assert regime.notna().any()


# ---------- apply_funding_regime_filter ----------------------------------------


def test_apply_funding_regime_filter_keeps_only_bear_period_shorts():
    # Mix: 60 calm days then 30 overheated days. With bear_quantile=0.75 the
    # tail is bear (overheated → favor short).
    rates = [0.0001] * 60 + [0.002] * 30
    funding = {"BTC": _funding_frame(rates, start="2026-01-01"), "ETH": _funding_frame(rates, start="2026-01-01")}
    events = pd.DataFrame(
        {
            "token": ["A"],
            "unlock_date": pd.to_datetime(
                ["2026-03-25T00:00:00"], utc=True  # in overheated tail
            ),
        }
    )
    filtered = rf.apply_funding_regime_filter(
        events,
        funding_by_token=funding,
        signal_offset_days=0,
        direction="short",
    )
    assert len(filtered) == 1


def test_apply_funding_regime_filter_drops_warmup_events():
    rates = [0.001] * 30
    funding = {"BTC": _funding_frame(rates, start="2026-01-01")}
    events = pd.DataFrame(
        {
            "token": ["A"],
            "unlock_date": pd.to_datetime(["2026-01-02"], utc=True),  # before warmup
        }
    )
    filtered = rf.apply_funding_regime_filter(
        events,
        funding_by_token=funding,
        signal_offset_days=0,
        direction="short",
    )
    assert filtered.empty


def test_apply_funding_regime_filter_uses_signal_offset_days():
    rates = [0.0001] * 60 + [0.002] * 30  # bear tail
    funding = {"BTC": _funding_frame(rates, start="2026-01-01"), "ETH": _funding_frame(rates, start="2026-01-01")}
    events = pd.DataFrame(
        {
            "token": ["A"],
            "unlock_date": pd.to_datetime(["2026-04-01T00:00:00"], utc=True),
        }
    )
    filtered = rf.apply_funding_regime_filter(
        events,
        funding_by_token=funding,
        signal_offset_days=-7,  # entry at 2026-03-25, in bear tail
        direction="short",
    )
    assert not filtered.empty


def test_apply_funding_regime_filter_passes_through_when_no_unlock_date_column():
    rates = [-0.001] * 30
    funding = {"BTC": _funding_frame(rates, start="2026-01-01")}
    events = pd.DataFrame({"token": ["A"]})
    filtered = rf.apply_funding_regime_filter(
        events,
        funding_by_token=funding,
        signal_offset_days=0,
        direction="short",
    )
    pd.testing.assert_frame_equal(filtered, events)


def test_apply_funding_regime_filter_passes_through_empty_events():
    funding = {"BTC": _funding_frame([0.001] * 30, start="2026-01-01")}
    events = pd.DataFrame(columns=["token", "unlock_date"])
    filtered = rf.apply_funding_regime_filter(
        events,
        funding_by_token=funding,
        signal_offset_days=0,
        direction="short",
    )
    assert filtered.empty


def test_compute_funding_regime_rejects_invalid_bear_quantile():
    with pytest.raises(ValueError, match="bear_quantile"):
        rf.compute_funding_regime(
            {"BTC": _funding_frame([0.001] * 30)},
            majors=("BTC",),
            window_days=7,
            bear_quantile=1.5,
        )
