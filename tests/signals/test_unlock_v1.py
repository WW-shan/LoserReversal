from __future__ import annotations

import pandas as pd
import pytest

from signals.unlock_v1 import unlock_short_signal


def _prices(start: str = "2026-01-01", periods: int = 45) -> pd.Series:
    index = pd.date_range(start, periods=periods, freq="1D", tz="UTC")
    return pd.Series(range(periods), index=index, dtype="float64", name="close")


def _events(rows: list[dict]) -> pd.DataFrame:
    defaults = {
        "coingecko_id": "example-token",
        "unlock_pct": 0.05,
        "category": "team",
        "has_hl_perp": True,
    }
    return pd.DataFrame([{**defaults, **row} for row in rows])


def test_single_event_emits_entry_before_unlock_and_exit_on_unlock():
    prices = {"ARB": _prices()}
    events = _events([{"token": "ARB", "unlock_date": pd.Timestamp("2026-01-15T00:00:00Z")}])

    result = unlock_short_signal(events, prices)

    entries, exits = result["ARB"]
    assert bool(entries.loc["2026-01-08"])
    assert bool(exits.loc["2026-01-15"])
    assert entries.sum() == 1
    assert exits.sum() == 1
    assert entries.index.equals(prices["ARB"].index)
    assert exits.index.equals(prices["ARB"].index)


def test_event_below_min_unlock_pct_omits_token():
    prices = {"ARB": _prices()}
    events = _events(
        [
            {
                "token": "ARB",
                "unlock_date": pd.Timestamp("2026-01-15T00:00:00Z"),
                "unlock_pct": 0.01,
            }
        ]
    )

    assert unlock_short_signal(events, prices) == {}


def test_requires_hyperliquid_perp_by_default():
    prices = {"ARB": _prices()}
    events = _events(
        [
            {
                "token": "ARB",
                "unlock_date": pd.Timestamp("2026-01-15T00:00:00Z"),
                "has_hl_perp": False,
            }
        ]
    )

    assert unlock_short_signal(events, prices) == {}


def test_can_include_token_without_hyperliquid_perp_when_not_required():
    prices = {"ARB": _prices()}
    events = _events(
        [
            {
                "token": "ARB",
                "unlock_date": pd.Timestamp("2026-01-15T00:00:00Z"),
                "has_hl_perp": False,
            }
        ]
    )

    result = unlock_short_signal(events, prices, require_hl_perp=False)

    assert set(result) == {"ARB"}


def test_two_spaced_events_emit_two_non_overlapping_pairs():
    prices = {"ARB": _prices()}
    events = _events(
        [
            {"token": "ARB", "unlock_date": pd.Timestamp("2026-01-15T00:00:00Z")},
            {"token": "ARB", "unlock_date": pd.Timestamp("2026-01-25T00:00:00Z")},
        ]
    )

    entries, exits = unlock_short_signal(events, prices)["ARB"]

    assert bool(entries.loc["2026-01-08"])
    assert bool(exits.loc["2026-01-15"])
    assert bool(entries.loc["2026-01-18"])
    assert bool(exits.loc["2026-01-25"])
    assert entries.sum() == 2
    assert exits.sum() == 2


def test_overlapping_second_event_is_skipped():
    prices = {"ARB": _prices()}
    events = _events(
        [
            {"token": "ARB", "unlock_date": pd.Timestamp("2026-01-15T00:00:00Z")},
            {"token": "ARB", "unlock_date": pd.Timestamp("2026-01-20T00:00:00Z")},
        ]
    )

    entries, exits = unlock_short_signal(events, prices)["ARB"]

    assert bool(entries.loc["2026-01-08"])
    assert bool(exits.loc["2026-01-15"])
    assert entries.sum() == 1
    assert exits.sum() == 1


def test_multiple_tokens_returns_only_qualifying_tokens():
    prices = {"ARB": _prices(), "APT": _prices(), "BTC": _prices()}
    events = _events(
        [
            {"token": "ARB", "unlock_date": pd.Timestamp("2026-01-15T00:00:00Z")},
            {
                "token": "APT",
                "unlock_date": pd.Timestamp("2026-01-16T00:00:00Z"),
                "unlock_pct": 0.01,
            },
            {
                "token": "BTC",
                "unlock_date": pd.Timestamp("2026-01-17T00:00:00Z"),
                "has_hl_perp": False,
            },
        ]
    )

    assert set(unlock_short_signal(events, prices)) == {"ARB"}


def test_event_outside_price_index_is_skipped_while_other_events_are_processed():
    prices = {"ARB": _prices()}
    events = _events(
        [
            {"token": "ARB", "unlock_date": pd.Timestamp("2025-12-25T00:00:00Z")},
            {"token": "ARB", "unlock_date": pd.Timestamp("2026-01-15T00:00:00Z")},
        ]
    )

    entries, exits = unlock_short_signal(events, prices)["ARB"]

    assert bool(entries.loc["2026-01-08"])
    assert bool(exits.loc["2026-01-15"])
    assert entries.sum() == 1
    assert exits.sum() == 1


def test_pre_window_days_must_be_positive():
    prices = {"ARB": _prices()}
    events = _events([{"token": "ARB", "unlock_date": pd.Timestamp("2026-01-15T00:00:00Z")}])

    for pre_window_days in [0, -1]:
        with pytest.raises(ValueError):
            unlock_short_signal(events, prices, pre_window_days=pre_window_days)


def test_naive_price_index_matches_utc_price_index_without_mutating_caller():
    aware_prices = _prices()
    naive_prices = aware_prices.copy()
    naive_prices.index = naive_prices.index.tz_localize(None)
    events = _events([{"token": "ARB", "unlock_date": pd.Timestamp("2026-01-15T00:00:00Z")}])

    aware_entries, aware_exits = unlock_short_signal(events, {"ARB": aware_prices})["ARB"]
    naive_entries, naive_exits = unlock_short_signal(events, {"ARB": naive_prices})["ARB"]

    assert naive_prices.index.tz is None
    assert naive_entries.equals(aware_entries)
    assert naive_exits.equals(aware_exits)
