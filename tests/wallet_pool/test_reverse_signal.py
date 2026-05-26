from __future__ import annotations

import pandas as pd
import pytest

from wallet_pool.reverse_signal import ReverseScoreConfig, compute_reverse_alpha_score


def _fill(
    *,
    time: str = "2026-05-26T12:00:00Z",
    px: float = 100.0,
    sz: float = 1.0,
    leverage: float = 1.0,
) -> dict[str, object]:
    return {
        "fill_id": "fill-1",
        "coin": "BTC",
        "time": pd.Timestamp(time, tz="UTC"),
        "px": px,
        "sz": sz,
        "leverage": leverage,
    }


def test_compute_reverse_alpha_score_returns_base_when_no_axis_matches() -> None:
    score = compute_reverse_alpha_score(
        _fill(),
        wallet_account_value=10_000.0,
        funding_context={"funding_zscore": 0.0},
        config=ReverseScoreConfig(),
    )

    assert score == pytest.approx(1.0)


def test_compute_reverse_alpha_score_applies_oversized_first_threshold() -> None:
    score = compute_reverse_alpha_score(
        _fill(px=100.0, sz=5.0),
        wallet_account_value=10_000.0,
        funding_context={"funding_zscore": 0.0},
        config=ReverseScoreConfig(),
    )

    assert score == pytest.approx(1.5)


def test_compute_reverse_alpha_score_applies_oversized_second_threshold_cumulatively() -> None:
    score = compute_reverse_alpha_score(
        _fill(px=100.0, sz=10.0),
        wallet_account_value=10_000.0,
        funding_context={"funding_zscore": 0.0},
        config=ReverseScoreConfig(),
    )

    assert score == pytest.approx(3.0)


def test_compute_reverse_alpha_score_applies_leverage_first_threshold() -> None:
    score = compute_reverse_alpha_score(
        _fill(leverage=10.0),
        wallet_account_value=10_000.0,
        funding_context={"funding_zscore": 0.0},
        config=ReverseScoreConfig(),
    )

    assert score == pytest.approx(1.3)


def test_compute_reverse_alpha_score_applies_leverage_second_threshold_cumulatively() -> None:
    score = compute_reverse_alpha_score(
        _fill(leverage=20.0),
        wallet_account_value=10_000.0,
        funding_context={"funding_zscore": 0.0},
        config=ReverseScoreConfig(),
    )

    assert score == pytest.approx(1.3 * 1.6)


def test_compute_reverse_alpha_score_applies_positive_funding_extreme() -> None:
    score = compute_reverse_alpha_score(
        _fill(),
        wallet_account_value=10_000.0,
        funding_context={"funding_zscore": 2.0},
        config=ReverseScoreConfig(),
    )

    assert score == pytest.approx(1.4)


def test_compute_reverse_alpha_score_applies_negative_funding_extreme() -> None:
    score = compute_reverse_alpha_score(
        _fill(),
        wallet_account_value=10_000.0,
        funding_context={"funding_zscore": -2.1},
        config=ReverseScoreConfig(),
    )

    assert score == pytest.approx(1.4)


def test_compute_reverse_alpha_score_applies_asian_session_start() -> None:
    score = compute_reverse_alpha_score(
        _fill(time="2026-05-26T00:00:00Z"),
        wallet_account_value=10_000.0,
        funding_context={"funding_zscore": 0.0},
        config=ReverseScoreConfig(),
    )

    assert score == pytest.approx(1.2)


def test_compute_reverse_alpha_score_excludes_asian_session_end() -> None:
    score = compute_reverse_alpha_score(
        _fill(time="2026-05-26T08:00:00Z"),
        wallet_account_value=10_000.0,
        funding_context={"funding_zscore": 0.0},
        config=ReverseScoreConfig(),
    )

    assert score == pytest.approx(1.0)


def test_compute_reverse_alpha_score_applies_funding_settle_window() -> None:
    score = compute_reverse_alpha_score(
        _fill(time="2026-05-26T15:45:00Z"),
        wallet_account_value=10_000.0,
        funding_context={"funding_zscore": 0.0},
        config=ReverseScoreConfig(),
    )

    assert score == pytest.approx(1.2)


def test_compute_reverse_alpha_score_multiplies_all_axes() -> None:
    score = compute_reverse_alpha_score(
        _fill(time="2026-05-26T01:00:00Z", px=100.0, sz=10.0, leverage=20.0),
        wallet_account_value=10_000.0,
        funding_context={"funding_zscore": -2.0},
        config=ReverseScoreConfig(),
    )

    assert score == pytest.approx(3.0 * 1.3 * 1.6 * 1.4 * 1.2)


def test_compute_reverse_alpha_score_ignores_missing_funding_context() -> None:
    score = compute_reverse_alpha_score(
        _fill(),
        wallet_account_value=10_000.0,
        funding_context=None,
        config=ReverseScoreConfig(),
    )

    assert score == pytest.approx(1.0)
