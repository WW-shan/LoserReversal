from __future__ import annotations

import pandas as pd
import pytest

from signals._unlock_common import emit_pair_signals, filter_events


def _prices(start: str = "2026-01-01", periods: int = 45) -> pd.Series:
    index = pd.date_range(start, periods=periods, freq="1D", tz="UTC")
    return pd.Series(range(periods), index=index, dtype="float64", name="close")


def _events(rows: list[dict]) -> pd.DataFrame:
    defaults = {
        "token": "ARB",
        "unlock_date": pd.Timestamp("2026-01-15T00:00:00Z"),
        "unlock_pct": 0.05,
        "category": "team",
        "has_hl_perp": True,
        "vesting_type": "cliff",
    }
    return pd.DataFrame([{**defaults, **row} for row in rows])


def _coverage(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_filter_events_drops_low_pct():
    events = _events([{"token": "ARB", "unlock_pct": 0.01}])

    result = filter_events(events, min_unlock_pct=0.02, require_hl_perp=True, coverage=None)

    assert result.empty


def test_filter_events_drops_non_hl_when_required():
    events = _events([{"token": "ARB", "has_hl_perp": False}])

    result = filter_events(events, min_unlock_pct=0.02, require_hl_perp=True, coverage=None)

    assert result.empty


def test_filter_events_drops_failed_coverage_when_provided():
    events = _events(
        [
            {"token": "ARB", "unlock_date": pd.Timestamp("2026-01-15T00:00:00Z")},
            {"token": "APT", "unlock_date": pd.Timestamp("2026-01-16T00:00:00Z")},
        ]
    )
    coverage = _coverage(
        [
            {"token": "ARB", "unlock_date": "2026-01-15", "coverage_status": "ok"},
            {
                "token": "APT",
                "unlock_date": "2026-01-16",
                "coverage_status": "insufficient_pre_days",
            },
        ]
    )

    result = filter_events(events, min_unlock_pct=0.02, require_hl_perp=True, coverage=coverage)

    assert result["token"].tolist() == ["ARB"]


def test_filter_events_no_op_when_coverage_none():
    events = _events(
        [
            {"token": "ARB", "unlock_date": pd.Timestamp("2026-01-15T00:00:00Z")},
            {"token": "APT", "unlock_date": pd.Timestamp("2026-01-16T00:00:00Z")},
        ]
    )

    result = filter_events(events, min_unlock_pct=0.02, require_hl_perp=True, coverage=None)

    assert result["token"].tolist() == ["ARB", "APT"]


def test_filter_events_missing_schema_column_returns_empty_frame():
    events = _events([{"token": "ARB"}]).drop(columns=["vesting_type"])

    result = filter_events(events, min_unlock_pct=0.02, require_hl_perp=True, coverage=None)

    assert result.empty


def test_filter_events_accepts_custom_required_columns():
    events = _events([{"token": "ARB"}]).drop(columns=["category", "vesting_type"])

    result = filter_events(
        events,
        min_unlock_pct=0.02,
        require_hl_perp=True,
        coverage=None,
        required_columns={"token", "unlock_date", "unlock_pct", "has_hl_perp"},
    )

    assert result["token"].tolist() == ["ARB"]


def test_emit_pair_signals_aligns_to_price_index():
    prices = {"ARB": _prices()}
    events = _events([{"token": "ARB", "unlock_date": pd.Timestamp("2026-01-15T00:00:00Z")}])

    entries, exits = emit_pair_signals(
        events=events,
        prices=prices,
        entry_offset_days=-7,
        exit_offset_days=0,
    )["ARB"]

    assert bool(entries.loc["2026-01-08"])
    assert bool(exits.loc["2026-01-15"])
    assert entries.index.equals(prices["ARB"].index)


def test_emit_pair_signals_skips_unalignable_event():
    prices = {"ARB": _prices()}
    events = _events([{"token": "ARB", "unlock_date": pd.Timestamp("2026-02-20T00:00:00Z")}])

    assert (
        emit_pair_signals(
            events=events,
            prices=prices,
            entry_offset_days=-7,
            exit_offset_days=0,
        )
        == {}
    )


def test_emit_pair_signals_negative_entry_offset_works():
    prices = {"ARB": _prices()}
    events = _events([{"token": "ARB", "unlock_date": pd.Timestamp("2026-01-15T00:00:00Z")}])

    entries, exits = emit_pair_signals(
        events=events,
        prices=prices,
        entry_offset_days=-3,
        exit_offset_days=0,
    )["ARB"]

    assert bool(entries.loc["2026-01-12"])
    assert bool(exits.loc["2026-01-15"])


def test_emit_pair_signals_positive_exit_offset_works():
    prices = {"ARB": _prices()}
    events = _events([{"token": "ARB", "unlock_date": pd.Timestamp("2026-01-15T00:00:00Z")}])

    entries, exits = emit_pair_signals(
        events=events,
        prices=prices,
        entry_offset_days=3,
        exit_offset_days=14,
    )["ARB"]

    assert bool(entries.loc["2026-01-18"])
    assert bool(exits.loc["2026-01-29"])


def test_emit_pair_signals_requires_both_offsets():
    prices = {"ARB": _prices()}
    events = _events([{"token": "ARB", "unlock_date": pd.Timestamp("2026-01-15T00:00:00Z")}])

    with pytest.raises(ValueError, match="entry_offset_days.*exit_offset_days"):
        emit_pair_signals(
            events=events,
            prices=prices,
            entry_offset_days=-7,
        )


def test_emit_pair_signals_rejects_non_increasing_offsets():
    prices = {"ARB": _prices()}
    events = _events([{"token": "ARB", "unlock_date": pd.Timestamp("2026-01-15T00:00:00Z")}])

    with pytest.raises(ValueError, match=r"exit_offset_days \(0\) must be > entry_offset_days \(0\)"):
        emit_pair_signals(
            events=events,
            prices=prices,
            entry_offset_days=0,
            exit_offset_days=0,
        )


def test_emit_pair_signals_rejects_non_increasing_offsets_before_empty_guard():
    prices = {"ARB": _prices()}
    events = pd.DataFrame(columns=["token", "unlock_date"])

    with pytest.raises(ValueError, match=r"exit_offset_days \(0\) must be > entry_offset_days \(0\)"):
        emit_pair_signals(
            events=events,
            prices=prices,
            entry_offset_days=0,
            exit_offset_days=0,
        )


def test_emit_pair_signals_skips_overlap():
    prices = {"ARB": _prices()}
    events = _events(
        [
            {"token": "ARB", "unlock_date": pd.Timestamp("2026-01-15T00:00:00Z")},
            {"token": "ARB", "unlock_date": pd.Timestamp("2026-01-20T00:00:00Z")},
        ]
    )

    entries, exits = emit_pair_signals(
        events=events,
        prices=prices,
        entry_offset_days=-7,
        exit_offset_days=0,
    )["ARB"]

    assert bool(entries.loc["2026-01-08"])
    assert bool(exits.loc["2026-01-15"])
    assert entries.sum() == 1
    assert exits.sum() == 1
