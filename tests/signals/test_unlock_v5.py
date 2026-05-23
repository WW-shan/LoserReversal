from __future__ import annotations

import pandas as pd
import pytest

from signals.unlock_v5 import unlock_reversal_long


def _prices(start: str = "2026-01-01", periods: int = 80) -> pd.Series:
    index = pd.date_range(start, periods=periods, freq="1D", tz="UTC")
    return pd.Series(range(periods), index=index, dtype="float64", name="close")


def _events(rows: list[dict]) -> pd.DataFrame:
    defaults = {
        "coingecko_id": "example-token",
        "unlock_pct": 0.05,
        "category": "team",
        "has_hl_perp": True,
        "vesting_type": "cliff",
    }
    return pd.DataFrame([{**defaults, **row} for row in rows])


def test_single_event_emits_entry_three_days_after_and_exit_fourteen_days_after_unlock():
    prices = {"ARB": _prices()}
    events = _events([{"token": "ARB", "unlock_date": pd.Timestamp("2026-01-15T00:00:00Z")}])

    result = unlock_reversal_long(events, prices)

    entries, exits = result["ARB"]
    assert bool(entries.loc["2026-01-18"])
    assert bool(exits.loc["2026-01-29"])
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

    assert unlock_reversal_long(events, prices) == {}


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

    assert unlock_reversal_long(events, prices) == {}


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

    result = unlock_reversal_long(events, prices, require_hl_perp=False)

    assert set(result) == {"ARB"}


def test_two_spaced_events_emit_two_non_overlapping_pairs():
    prices = {"ARB": _prices()}
    events = _events(
        [
            {"token": "ARB", "unlock_date": pd.Timestamp("2026-01-15T00:00:00Z")},
            {"token": "ARB", "unlock_date": pd.Timestamp("2026-02-10T00:00:00Z")},
        ]
    )

    entries, exits = unlock_reversal_long(events, prices)["ARB"]

    assert bool(entries.loc["2026-01-18"])
    assert bool(exits.loc["2026-01-29"])
    assert bool(entries.loc["2026-02-13"])
    assert bool(exits.loc["2026-02-24"])
    assert entries.sum() == 2
    assert exits.sum() == 2


def test_overlapping_second_event_is_skipped():
    prices = {"ARB": _prices()}
    events = _events(
        [
            {"token": "ARB", "unlock_date": pd.Timestamp("2026-01-15T00:00:00Z")},
            {"token": "ARB", "unlock_date": pd.Timestamp("2026-01-24T00:00:00Z")},
        ]
    )

    entries, exits = unlock_reversal_long(events, prices)["ARB"]

    assert bool(entries.loc["2026-01-18"])
    assert bool(exits.loc["2026-01-29"])
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

    assert set(unlock_reversal_long(events, prices)) == {"ARB"}


def test_event_outside_price_index_is_skipped_while_other_events_are_processed():
    prices = {"ARB": _prices()}
    events = _events(
        [
            {"token": "ARB", "unlock_date": pd.Timestamp("2026-03-20T00:00:00Z")},
            {"token": "ARB", "unlock_date": pd.Timestamp("2026-01-15T00:00:00Z")},
        ]
    )

    entries, exits = unlock_reversal_long(events, prices)["ARB"]

    assert bool(entries.loc["2026-01-18"])
    assert bool(exits.loc["2026-01-29"])
    assert entries.sum() == 1
    assert exits.sum() == 1


def test_naive_price_index_matches_utc_price_index_without_mutating_caller():
    aware_prices = _prices()
    naive_prices = aware_prices.copy()
    naive_prices.index = naive_prices.index.tz_localize(None)
    events = _events([{"token": "ARB", "unlock_date": pd.Timestamp("2026-01-15T00:00:00Z")}])

    aware_entries, aware_exits = unlock_reversal_long(events, {"ARB": aware_prices})["ARB"]
    naive_entries, naive_exits = unlock_reversal_long(events, {"ARB": naive_prices})["ARB"]

    assert naive_prices.index.tz is None
    assert naive_entries.equals(aware_entries)
    assert naive_exits.equals(aware_exits)


def test_post_offsets_must_be_positive_and_exit_after_entry():
    prices = {"ARB": _prices()}
    events = _events([{"token": "ARB", "unlock_date": pd.Timestamp("2026-01-15T00:00:00Z")}])

    with pytest.raises(ValueError):
        unlock_reversal_long(events, prices, post_entry_days=0)
    with pytest.raises(ValueError):
        unlock_reversal_long(events, prices, post_exit_days=3)
    with pytest.raises(ValueError):
        unlock_reversal_long(events, prices, post_entry_days=5, post_exit_days=4)


def test_entry_happens_after_unlock_date():
    prices = {"ARB": _prices()}
    unlock_date = pd.Timestamp("2026-01-15T00:00:00Z")
    events = _events([{"token": "ARB", "unlock_date": unlock_date}])

    entries, _ = unlock_reversal_long(events, prices)["ARB"]
    entry_ts = entries[entries].index[0]

    assert entry_ts > unlock_date


def test_coverage_parameter_keeps_only_ok_events():
    prices = {"ARB": _prices(), "APT": _prices()}
    events = _events(
        [
            {"token": "ARB", "unlock_date": pd.Timestamp("2026-01-15T00:00:00Z")},
            {"token": "APT", "unlock_date": pd.Timestamp("2026-01-16T00:00:00Z")},
        ]
    )
    coverage = pd.DataFrame(
        [
            {"token": "ARB", "unlock_date": "2026-01-15", "coverage_status": "ok"},
            {
                "token": "APT",
                "unlock_date": "2026-01-16",
                "coverage_status": "insufficient_pre_days",
            },
        ]
    )

    result = unlock_reversal_long(events, prices, coverage=coverage)

    assert set(result) == {"ARB"}
