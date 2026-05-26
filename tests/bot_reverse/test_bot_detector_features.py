from __future__ import annotations

import pandas as pd
import pytest


def _fill_row(
    time: str,
    *,
    coin: str = "BTC",
    sz: float = 1_000.0,
) -> dict[str, object]:
    return {
        "time": pd.Timestamp(time, tz="UTC"),
        "coin": coin,
        "side": "B",
        "dir": "Open Long",
        "px": 100.0,
        "sz": sz,
        "start_position": 0.0,
        "closed_pnl": 0.0,
        "fee": 0.0,
        "oid": 1,
        "tid": 1,
        "hash": "0x1",
        "crossed": False,
        "liquidation": False,
    }


def _fills_df(rows: list[dict[str, object]]) -> pd.DataFrame:
    if not rows:
        empty = pd.DataFrame(columns=list(_fill_row("2026-01-01T00:00:00Z").keys()))
        empty["time"] = pd.to_datetime(empty["time"], utc=True)
        return empty.set_index("time")
    frame = pd.DataFrame(rows)
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    return frame.set_index("time").sort_index()


def test_compute_bot_features_empty_fills_returns_zeroed_features() -> None:
    from bot_reverse.bot_detector import compute_bot_features

    features = compute_bot_features(_fills_df([]), account_value=10_000.0)

    assert features == {
        "tx_hour_entropy": 0.0,
        "size_uniformity_cv": 0.0,
        "coin_diversity": 0.0,
        "avg_session_gap_minutes": 0.0,
        "round_number_pct": 0.0,
    }


def test_compute_bot_features_single_trade_has_no_session_gap() -> None:
    from bot_reverse.bot_detector import compute_bot_features

    fills = _fills_df([_fill_row("2026-05-01T00:00:00Z", coin="BTC", sz=1_000.0)])

    features = compute_bot_features(fills, account_value=10_000.0)

    assert features["tx_hour_entropy"] == 0.0
    assert features["size_uniformity_cv"] == 0.0
    assert features["coin_diversity"] == pytest.approx(1.0)
    assert features["avg_session_gap_minutes"] == 0.0
    assert features["round_number_pct"] == pytest.approx(1.0)


def test_compute_bot_features_hour_entropy_is_high_for_round_the_clock_distribution() -> None:
    from bot_reverse.bot_detector import compute_bot_features

    fills = _fills_df(
        [
            _fill_row((pd.Timestamp("2026-05-01T00:00:00Z") + pd.Timedelta(hours=i)).isoformat())
            for i in range(24)
        ]
    )

    features = compute_bot_features(fills, account_value=10_000.0)

    assert features["tx_hour_entropy"] == pytest.approx(1.0)


def test_compute_bot_features_hour_entropy_is_low_for_single_hour_burst() -> None:
    from bot_reverse.bot_detector import compute_bot_features

    fills = _fills_df(
        [
            _fill_row((pd.Timestamp("2026-05-01T03:00:00Z") + pd.Timedelta(minutes=i)).isoformat())
            for i in range(12)
        ]
    )

    features = compute_bot_features(fills, account_value=10_000.0)

    assert features["tx_hour_entropy"] == pytest.approx(0.0)


def test_compute_bot_features_size_uniformity_cv_is_std_over_mean() -> None:
    from bot_reverse.bot_detector import compute_bot_features

    fills = _fills_df(
        [
            _fill_row("2026-05-01T00:00:00Z", sz=500.0),
            _fill_row("2026-05-01T01:00:00Z", sz=1_000.0),
            _fill_row("2026-05-01T02:00:00Z", sz=1_500.0),
        ]
    )

    features = compute_bot_features(fills, account_value=10_000.0)

    assert features["size_uniformity_cv"] == pytest.approx(0.4082, abs=1e-3)


def test_compute_bot_features_size_uniformity_cv_zero_for_uniform_sizes() -> None:
    from bot_reverse.bot_detector import compute_bot_features

    fills = _fills_df(
        [
            _fill_row("2026-05-01T00:00:00Z", sz=1_000.0),
            _fill_row("2026-05-01T01:00:00Z", sz=1_000.0),
            _fill_row("2026-05-01T02:00:00Z", sz=1_000.0),
        ]
    )

    features = compute_bot_features(fills, account_value=10_000.0)

    assert features["size_uniformity_cv"] == pytest.approx(0.0, abs=1e-9)


def test_compute_bot_features_coin_diversity_is_unique_coins_over_trades() -> None:
    from bot_reverse.bot_detector import compute_bot_features

    fills = _fills_df(
        [
            _fill_row("2026-05-01T00:00:00Z", coin="BTC"),
            _fill_row("2026-05-01T01:00:00Z", coin="BTC"),
            _fill_row("2026-05-01T02:00:00Z", coin="ETH"),
            _fill_row("2026-05-01T03:00:00Z", coin="SOL"),
        ]
    )

    features = compute_bot_features(fills, account_value=10_000.0)

    assert features["coin_diversity"] == pytest.approx(0.75)


def test_compute_bot_features_session_gap_uses_median_minutes() -> None:
    from bot_reverse.bot_detector import compute_bot_features

    fills = _fills_df(
        [
            _fill_row("2026-05-01T00:00:00Z"),
            _fill_row("2026-05-01T00:10:00Z"),
            _fill_row("2026-05-01T01:10:00Z"),
            _fill_row("2026-05-01T05:10:00Z"),
        ]
    )

    features = compute_bot_features(fills, account_value=10_000.0)

    assert features["avg_session_gap_minutes"] == pytest.approx(60.0)


def test_compute_bot_features_round_number_pct_counts_large_integer_sizes() -> None:
    from bot_reverse.bot_detector import compute_bot_features

    fills = _fills_df(
        [
            _fill_row("2026-05-01T00:00:00Z", sz=1_000.0),
            _fill_row("2026-05-01T01:00:00Z", sz=5_000.0),
            _fill_row("2026-05-01T02:00:00Z", sz=123.45),
            _fill_row("2026-05-01T03:00:00Z", sz=77.7),
        ]
    )

    features = compute_bot_features(fills, account_value=10_000.0)

    assert features["round_number_pct"] == pytest.approx(0.5)


def test_compute_bot_features_round_number_pct_uses_all_trades_as_denominator() -> None:
    from bot_reverse.bot_detector import compute_bot_features

    fills = _fills_df(
        [
            _fill_row("2026-05-01T00:00:00Z", sz=1_000.0),
            _fill_row("2026-05-01T01:00:00Z", sz=0.0),
            _fill_row("2026-05-01T02:00:00Z", sz=-100.0),
            _fill_row("2026-05-01T03:00:00Z", sz=float("nan")),
        ]
    )

    features = compute_bot_features(fills, account_value=10_000.0)

    assert features["round_number_pct"] == pytest.approx(0.25)


def test_compute_bot_features_accepts_time_column_without_datetime_index() -> None:
    from bot_reverse.bot_detector import compute_bot_features

    fills = pd.DataFrame(
        [
            _fill_row("2026-05-01T00:00:00Z", sz=1_000.0),
            _fill_row("2026-05-01T01:00:00Z", sz=1_000.0),
        ]
    )

    features = compute_bot_features(fills, account_value=10_000.0)

    assert features["avg_session_gap_minutes"] == pytest.approx(60.0)
    assert features["round_number_pct"] == pytest.approx(1.0)
