from __future__ import annotations

import pandas as pd
import pytest

from wallet_pool.reverse_signal import (
    ReverseScoreConfig,
    compute_reverse_alpha_score,
    score_wallet_fills,
    wallet_confidence_weight,
)


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


def test_compute_reverse_alpha_score_applies_infinite_funding_extreme() -> None:
    score = compute_reverse_alpha_score(
        _fill(),
        wallet_account_value=10_000.0,
        funding_context={"funding_zscore": float("inf")},
        config=ReverseScoreConfig(),
    )

    assert score == pytest.approx(1.4)


def test_compute_reverse_alpha_score_derives_leverage_from_notional_when_missing() -> None:
    fill = {
        "fill_id": "fill-1",
        "coin": "BTC",
        "time": pd.Timestamp("2026-05-26T12:00:00Z"),
        "px": 100.0,
        "sz": 1_000.0,
    }

    score = compute_reverse_alpha_score(
        fill,
        wallet_account_value=10_000.0,
        funding_context={"funding_zscore": 0.0},
        config=ReverseScoreConfig(),
    )

    assert score == pytest.approx(3.0 * 1.3)


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


def _wallet_metrics(
    *,
    account_value: float = 10_000.0,
    loss_rate: float = 0.75,
    leverage: float = 12.5,
    n_trades: int = 125,
) -> dict[str, float]:
    return {
        "account_value": account_value,
        "realized_loss_rate_90d": loss_rate,
        "leverage_avg_90d": leverage,
        "n_trades_90d": n_trades,
    }


def _fills_frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(
            {
                "fill_id": pd.Series(dtype="string"),
                "coin": pd.Series(dtype="string"),
                "time": pd.Series(dtype="datetime64[ns, UTC]"),
                "px": pd.Series(dtype="float64"),
                "sz": pd.Series(dtype="float64"),
                "leverage": pd.Series(dtype="float64"),
            }
        )
    frame = pd.DataFrame(rows)
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    return frame


def _funding_history() -> dict[str, pd.DataFrame]:
    frame = pd.DataFrame(
        {"funding_zscore": [0.0, 2.5]},
        index=pd.to_datetime(
            ["2026-05-26T08:00:00Z", "2026-05-26T11:00:00Z"],
            utc=True,
        ),
    )
    return {"BTC": frame}


def test_score_wallet_fills_returns_one_row_per_fill_with_components() -> None:
    fills = _fills_frame(
        [
            _fill(time="2026-05-26T12:00:00Z", px=100.0, sz=5.0, leverage=10.0),
            _fill(time="2026-05-26T14:00:00Z", px=100.0, sz=1.0, leverage=1.0),
        ]
    )
    fills.loc[1, "fill_id"] = "fill-2"

    scores = score_wallet_fills(
        fills,
        _wallet_metrics(),
        _funding_history(),
        config=ReverseScoreConfig(),
    )

    assert scores["fill_id"].tolist() == ["fill-1", "fill-2"]
    assert scores["score"].tolist() == pytest.approx([1.5 * 1.3 * 1.4, 1.4])
    assert scores["components"].iloc[0]["oversized_multiplier"] == pytest.approx(1.5)
    assert scores["components"].iloc[0]["leverage_multiplier"] == pytest.approx(1.3)
    assert scores["components"].iloc[0]["funding_extreme_multiplier"] == pytest.approx(1.4)
    assert scores["components"].iloc[0]["time_bucket_multiplier"] == pytest.approx(1.0)
    assert scores["components"].iloc[0]["risk_ratio"] == pytest.approx(0.05)
    assert scores["components"].iloc[0]["funding_zscore"] == pytest.approx(2.5)
    assert scores["components"].iloc[0]["wallet_confidence"] == pytest.approx(0.5)


def test_score_wallet_fills_handles_empty_fills() -> None:
    scores = score_wallet_fills(
        _fills_frame([]),
        _wallet_metrics(),
        funding_history={},
        config=ReverseScoreConfig(),
    )

    assert scores.empty
    assert scores.columns.tolist() == ["fill_id", "score", "components"]


def test_wallet_confidence_weight_scores_balanced_academic_metrics_at_half_confidence() -> None:
    assert wallet_confidence_weight(_wallet_metrics()) == pytest.approx(0.5)


def test_wallet_confidence_weight_clamps_strong_academic_metrics_to_one() -> None:
    metrics = _wallet_metrics(loss_rate=1.0, leverage=100.0, n_trades=1_000)

    assert wallet_confidence_weight(metrics) == pytest.approx(1.0)


def test_wallet_confidence_weight_returns_zero_for_missing_metrics() -> None:
    assert wallet_confidence_weight({}) == pytest.approx(0.0)
