from __future__ import annotations

import pandas as pd
import pytest


def _fill_row(
    time: pd.Timestamp,
    *,
    coin: str,
    sz: float,
) -> dict[str, object]:
    return {
        "time": time,
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
    frame = pd.DataFrame(rows)
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    return frame.set_index("time").sort_index()


def _bot_shaped_fills() -> pd.DataFrame:
    base = pd.Timestamp("2026-05-01T00:00:00Z")
    return _fills_df(
        [
            _fill_row(base + pd.Timedelta(hours=i), coin="BTC", sz=1_000.0)
            for i in range(24)
        ]
    )


def _human_shaped_fills() -> pd.DataFrame:
    base = pd.Timestamp("2026-05-01T00:00:00Z")
    coins = ["BTC", "ETH", "SOL", "HYPE", "DOGE", "XRP", "BNB", "SUI"]
    gaps = [0, 7, 31, 215, 377, 600, 980, 1_440]
    sizes = [127.43, 981.27, 53.81, 2_345.67, 410.19, 88.42, 1_579.31, 231.76]
    return _fills_df(
        [
            _fill_row(base + pd.Timedelta(minutes=gaps[i]), coin=coins[i], sz=sizes[i])
            for i in range(len(coins))
        ]
    )


def _balanced_features() -> dict[str, float]:
    return {
        "tx_hour_entropy": 0.575,
        "size_uniformity_cv": 0.40,
        "coin_diversity": 0.50,
        "avg_session_gap_minutes": 360.0,
        "round_number_pct": 0.45,
    }


def test_bot_shaped_fixture_scores_at_least_80_pct() -> None:
    from bot_reverse.bot_detector import compute_bot_features, is_bot_wallet, score_bot_likelihood

    features = compute_bot_features(_bot_shaped_fills(), account_value=25_000.0)

    assert score_bot_likelihood(features) >= 0.8
    assert is_bot_wallet(features) is True


def test_human_shaped_fixture_scores_at_most_30_pct() -> None:
    from bot_reverse.bot_detector import compute_bot_features, is_bot_wallet, score_bot_likelihood

    features = compute_bot_features(_human_shaped_fills(), account_value=25_000.0)

    assert score_bot_likelihood(features) <= 0.3
    assert is_bot_wallet(features) is False


def test_score_bot_likelihood_returns_zero_for_empty_features() -> None:
    from bot_reverse.bot_detector import score_bot_likelihood

    assert score_bot_likelihood({}) == 0.0


def test_score_bot_likelihood_clamps_to_unit_interval() -> None:
    from bot_reverse.bot_detector import score_bot_likelihood

    features = {
        "tx_hour_entropy": 10.0,
        "size_uniformity_cv": -1.0,
        "coin_diversity": -1.0,
        "avg_session_gap_minutes": -1.0,
        "round_number_pct": 10.0,
    }

    assert score_bot_likelihood(features) == pytest.approx(1.0)


def test_is_bot_wallet_default_threshold_is_inclusive() -> None:
    from bot_reverse.bot_detector import is_bot_wallet, score_bot_likelihood

    features = _balanced_features()

    assert score_bot_likelihood(features) == pytest.approx(0.5)
    assert is_bot_wallet(features) is True


def test_is_bot_wallet_respects_custom_threshold() -> None:
    from bot_reverse.bot_detector import is_bot_wallet

    features = _balanced_features()

    assert is_bot_wallet(features, threshold=0.6) is False


def test_score_bot_likelihood_ignores_nan_features() -> None:
    from bot_reverse.bot_detector import score_bot_likelihood

    features = {
        "tx_hour_entropy": float("nan"),
        "size_uniformity_cv": float("nan"),
        "coin_diversity": float("nan"),
        "avg_session_gap_minutes": float("nan"),
        "round_number_pct": float("nan"),
    }

    assert score_bot_likelihood(features) == 0.0
