from __future__ import annotations

import pandas as pd
import pytest

from signals.funding_extreme_v1 import funding_extreme_signal


def test_positive_z_extreme_triggers_short_signal():
    funding = _funding([0.0001] * 24 + [0.0010] + [0.0010] * 4)
    prices = _prices(funding)

    entries, exits, direction = funding_extreme_signal(
        {"BTC": funding},
        {"BTC": prices},
        lookback_days=2,
        hold_hours=4,
        require_min_history=1,
    )["BTC"]

    entry_time = pd.Timestamp("2026-01-02T00:00:00Z")
    assert entries.index.equals(prices.index)
    assert exits.index.equals(prices.index)
    assert direction.index.equals(prices.index)
    assert bool(entries.loc[entry_time])
    assert int(direction.loc[entry_time]) == -1


def test_negative_z_extreme_triggers_long_signal():
    funding = _funding([-0.0001] * 24 + [-0.0010] + [-0.0010] * 4)
    prices = _prices(funding)

    entries, _, direction = funding_extreme_signal(
        {"ETH": funding},
        {"ETH": prices},
        lookback_days=2,
        hold_hours=4,
        require_min_history=1,
    )["ETH"]

    entry_time = pd.Timestamp("2026-01-02T00:00:00Z")
    assert bool(entries.loc[entry_time])
    assert int(direction.loc[entry_time]) == 1


def test_signal_does_not_trigger_below_threshold():
    funding = _funding([0.0001] * 30)
    prices = _prices(funding)

    entries, exits, direction = funding_extreme_signal(
        {"BTC": funding},
        {"BTC": prices},
        lookback_days=2,
        require_min_history=1,
    )["BTC"]

    assert entries.sum() == 0
    assert exits.sum() == 0
    assert direction.abs().sum() == 0


def test_signal_does_not_trigger_during_warmup_lookback():
    funding = _funding([0.0001] * 5 + [0.0010] + [0.0010] * 4)
    prices = _prices(funding)

    entries, exits, direction = funding_extreme_signal(
        {"BTC": funding},
        {"BTC": prices},
        lookback_days=2,
        require_min_history=1,
    )["BTC"]

    assert entries.sum() == 0
    assert exits.sum() == 0
    assert direction.abs().sum() == 0


def test_max_hold_exit_after_hold_hours():
    funding = _funding([0.0001] * 24 + [0.0010] + [0.0010] * 8)
    prices = _prices(funding)

    _, exits, direction = funding_extreme_signal(
        {"BTC": funding},
        {"BTC": prices},
        lookback_days=2,
        hold_hours=4,
        mean_revert_z=0.0,
        require_min_history=1,
    )["BTC"]

    assert bool(exits.loc["2026-01-02T04:00:00Z"])
    assert int(direction.loc["2026-01-02T03:00:00Z"]) == -1


def test_mean_revert_exit_when_z_drops_below_threshold():
    funding = _funding([0.0001] * 24 + [0.0010] + [0.0001] * 8)
    prices = _prices(funding)

    _, exits, _ = funding_extreme_signal(
        {"BTC": funding},
        {"BTC": prices},
        lookback_days=2,
        hold_hours=8,
        mean_revert_z=0.5,
        require_min_history=1,
    )["BTC"]

    assert bool(exits.loc["2026-01-02T01:00:00Z"])
    assert not bool(exits.loc["2026-01-02T08:00:00Z"])


def test_overlapping_entry_skipped_until_prior_exits():
    funding = _funding([0.0001] * 24 + [0.0010, 0.0010] + [0.0001] * 6)
    prices = _prices(funding)

    entries, exits, _ = funding_extreme_signal(
        {"BTC": funding},
        {"BTC": prices},
        lookback_days=2,
        hold_hours=4,
        mean_revert_z=0.0,
        require_min_history=1,
    )["BTC"]

    assert entries.sum() == 1
    assert bool(entries.loc["2026-01-02T00:00:00Z"])
    assert bool(exits.loc["2026-01-02T04:00:00Z"])


def test_funding_timestamp_between_price_bars_enters_next_price_bar():
    funding = _funding([0.0001] * 24 + [0.0010] + [0.0010] * 4)
    funding.index = funding.index + pd.Timedelta(milliseconds=500)
    price_index = pd.date_range("2026-01-01", periods=len(funding) + 1, freq="1h", tz="UTC")
    prices = pd.Series(range(len(price_index)), index=price_index, dtype="float64", name="close")

    entries, _, direction = funding_extreme_signal(
        {"BTC": funding},
        {"BTC": prices},
        lookback_days=2,
        hold_hours=4,
        require_min_history=1,
    )["BTC"]

    assert not bool(entries.loc["2026-01-02T00:00:00Z"])
    assert bool(entries.loc["2026-01-02T01:00:00Z"])
    assert int(direction.loc["2026-01-02T01:00:00Z"]) == -1


def test_empty_funding_history_returns_empty_dict():
    assert funding_extreme_signal({}, {}) == {}


def test_invalid_z_threshold_raises():
    funding = _funding([0.0001] * 30)

    with pytest.raises(ValueError, match="z_threshold"):
        funding_extreme_signal({"BTC": funding}, {"BTC": _prices(funding)}, z_threshold=0)


def _funding(rates: list[float]) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=len(rates), freq="1h", tz="UTC")
    return pd.DataFrame(
        {
            "funding_rate": rates,
            "premium": [0.0] * len(rates),
        },
        index=pd.DatetimeIndex(index, name="timestamp"),
    )


def _prices(funding: pd.DataFrame) -> pd.Series:
    return pd.Series(range(len(funding)), index=funding.index, dtype="float64", name="close")
