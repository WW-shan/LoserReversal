from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import pytest

from wallet_pool.reverse_signal import (
    ReverseScoreConfig,
    compute_reverse_alpha_score,
    score_wallet_fills,
    wallet_confidence_weight,
)

FUNDING_MAX_BOOST = 1.4
FUNDING_TEMP = 0.5
TIME_MAX_BOOST = 1.2
TIME_PIVOT = 0.5
TIME_TEMP = 0.2


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def _funding_multiplier(zscore: float) -> float:
    if math.isinf(zscore):
        return FUNDING_MAX_BOOST
    magnitude = abs(zscore)
    if magnitude == 0:
        return 1.0
    return 1.0 + (FUNDING_MAX_BOOST - 1.0) * _sigmoid((magnitude - 2.0) / FUNDING_TEMP)


def _time_multiplier(signal: float = 1.0) -> float:
    return 1.0 + (TIME_MAX_BOOST - 1.0) * _sigmoid((signal - TIME_PIVOT) / TIME_TEMP)


def _trade_component(n_trades: int) -> float:
    return (math.log1p(n_trades) - math.log1p(50)) / (math.log1p(5000) - math.log1p(50))


def _fill(
    *,
    time: str = "2026-05-26T12:00:00Z",
    px: float = 100.0,
    sz: float = 1.0,
    leverage: float = 1.0,
    direction: str = "Open Long",
) -> dict[str, object]:
    return {
        "fill_id": "fill-1",
        "coin": "BTC",
        "time": pd.Timestamp(time, tz="UTC"),
        "dir": direction,
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

    assert score == pytest.approx(_funding_multiplier(2.0))


def test_compute_reverse_alpha_score_applies_negative_funding_extreme() -> None:
    score = compute_reverse_alpha_score(
        _fill(),
        wallet_account_value=10_000.0,
        funding_context={"funding_zscore": -2.1},
        config=ReverseScoreConfig(),
    )

    assert score == pytest.approx(_funding_multiplier(-2.1))


def test_compute_reverse_alpha_score_applies_infinite_funding_extreme() -> None:
    score = compute_reverse_alpha_score(
        _fill(),
        wallet_account_value=10_000.0,
        funding_context={"funding_zscore": float("inf")},
        config=ReverseScoreConfig(),
    )

    assert score == pytest.approx(FUNDING_MAX_BOOST)


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

    assert score == pytest.approx(_time_multiplier())


def test_compute_reverse_alpha_score_applies_tokyo_open_session_start() -> None:
    score = compute_reverse_alpha_score(
        _fill(time="2026-05-26T23:00:00Z"),
        wallet_account_value=10_000.0,
        funding_context={"funding_zscore": 0.0},
        config=ReverseScoreConfig(),
    )

    assert score == pytest.approx(_time_multiplier())


def test_compute_reverse_alpha_score_excludes_asian_session_end() -> None:
    score = compute_reverse_alpha_score(
        _fill(time="2026-05-26T07:00:00Z"),
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

    assert score == pytest.approx(_time_multiplier(0.5))


def test_compute_reverse_alpha_score_localizes_naive_fill_timestamp_to_utc() -> None:
    score = compute_reverse_alpha_score(
        {
            "fill_id": "fill-1",
            "coin": "BTC",
            "time": pd.Timestamp("2026-05-26 23:30:00"),
            "dir": "Open Long",
            "px": 100.0,
            "sz": 1.0,
            "leverage": 1.0,
        },
        wallet_account_value=10_000.0,
        funding_context={"funding_zscore": 0.0},
        config=ReverseScoreConfig(),
    )

    assert score == pytest.approx(_time_multiplier())


def test_compute_reverse_alpha_score_multiplies_all_axes() -> None:
    score = compute_reverse_alpha_score(
        _fill(time="2026-05-26T01:00:00Z", px=100.0, sz=10.0, leverage=20.0),
        wallet_account_value=10_000.0,
        funding_context={"funding_zscore": -2.0},
        config=ReverseScoreConfig(),
    )

    assert score == pytest.approx(3.0 * 1.3 * 1.6 * _funding_multiplier(-2.0) * _time_multiplier())


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
                "dir": pd.Series(dtype="string"),
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
    assert scores["time"].tolist() == [
        pd.Timestamp("2026-05-26T12:00:00Z"),
        pd.Timestamp("2026-05-26T14:00:00Z"),
    ]
    assert scores["dir"].tolist() == ["Open Long", "Open Long"]
    assert scores["reverse_side"].tolist() == ["short", "short"]
    assert scores["token"].tolist() == ["BTC", "BTC"]
    assert scores["score"].tolist() == pytest.approx(
        [1.5 * 1.3 * _funding_multiplier(2.5), _funding_multiplier(2.5)]
    )
    assert scores["components"].iloc[0]["oversized_multiplier"] == pytest.approx(1.5)
    assert scores["components"].iloc[0]["leverage_multiplier"] == pytest.approx(1.3)
    assert scores["components"].iloc[0]["funding_extreme_multiplier"] == pytest.approx(
        _funding_multiplier(2.5)
    )
    assert scores["components"].iloc[0]["time_bucket_multiplier"] == pytest.approx(1.0)
    assert scores["components"].iloc[0]["risk_ratio"] == pytest.approx(0.05)
    assert scores["components"].iloc[0]["funding_zscore"] == pytest.approx(2.5)
    assert scores["components"].iloc[0]["wallet_confidence"] == pytest.approx(
        wallet_confidence_weight(_wallet_metrics())
    )


def test_score_wallet_fills_handles_empty_fills() -> None:
    scores = score_wallet_fills(
        _fills_frame([]),
        _wallet_metrics(),
        funding_history={},
        config=ReverseScoreConfig(),
    )

    assert scores.empty
    assert scores.columns.tolist() == [
        "fill_id",
        "time",
        "dir",
        "reverse_side",
        "token",
        "score",
        "components",
    ]


def test_wallet_confidence_weight_log_scales_trade_component() -> None:
    assert wallet_confidence_weight(_wallet_metrics()) == pytest.approx(
        (0.5 + 0.5 + _trade_component(125)) / 3.0
    )


def test_wallet_confidence_weight_clamps_strong_academic_metrics_to_one() -> None:
    metrics = _wallet_metrics(loss_rate=1.0, leverage=100.0, n_trades=5_000)

    assert wallet_confidence_weight(metrics) == pytest.approx(1.0)


def test_wallet_confidence_weight_returns_zero_for_missing_metrics() -> None:
    assert wallet_confidence_weight({}) == pytest.approx(0.0)


def test_wallet_confidence_weight_keeps_high_trade_counts_discriminating() -> None:
    lower = wallet_confidence_weight(_wallet_metrics(loss_rate=1.0, leverage=20.0, n_trades=200))
    higher = wallet_confidence_weight(_wallet_metrics(loss_rate=1.0, leverage=20.0, n_trades=5_000))

    assert higher - lower > 0.15


def test_wallet_confidence_weight_actual_academic_pool_spans_half_point() -> None:
    pool_path = Path("data/parquet/academic_wallet_pool.parquet")
    if not pool_path.exists():
        pytest.skip("academic pool fixture is not present")

    pool = pd.read_parquet(pool_path)
    weights = [wallet_confidence_weight(row) for _, row in pool.iterrows()]

    assert len(weights) == 21
    assert max(weights) - min(weights) >= 0.5


def test_score_wallet_fills_uses_strictly_prior_funding_context_at_settle_boundary() -> None:
    fills = _fills_frame([_fill(time="2026-05-26T16:00:00Z")])
    funding = pd.DataFrame(
        {"funding_zscore": [1.25, 99.9]},
        index=pd.to_datetime(
            ["2026-05-26T08:00:00Z", "2026-05-26T16:00:00Z"],
            utc=True,
        ),
    )

    scores = score_wallet_fills(
        fills,
        _wallet_metrics(),
        {"BTC": funding},
        config=ReverseScoreConfig(),
    )

    assert scores["components"].iloc[0]["funding_zscore"] == pytest.approx(1.25)


def test_score_wallet_fills_uses_last_non_nan_precomputed_funding_zscore() -> None:
    fills = _fills_frame([_fill(time="2026-05-26T12:00:00Z")])
    funding = pd.DataFrame(
        {"funding_zscore": [2.5, float("nan")]},
        index=pd.to_datetime(
            ["2026-05-26T10:00:00Z", "2026-05-26T11:00:00Z"],
            utc=True,
        ),
    )

    scores = score_wallet_fills(
        fills,
        _wallet_metrics(),
        {"BTC": funding},
        config=ReverseScoreConfig(),
    )

    assert scores["components"].iloc[0]["funding_zscore"] == pytest.approx(2.5)


def test_score_wallet_fills_computes_funding_zscore_from_rolling_lookback() -> None:
    fills = _fills_frame([_fill(time="2026-05-26T12:00:00Z")])
    index = pd.date_range("2026-03-18T08:00:00Z", periods=70, freq="1D")
    funding = pd.DataFrame(
        {
            "funding_rate": [
                *[-1.0, 1.0] * 15,
                *[0.001 + step * 0.00005 for step in range(39)],
                0.020,
            ]
        },
        index=index,
    )

    scores = score_wallet_fills(
        fills,
        _wallet_metrics(),
        {"BTC": funding},
        config=ReverseScoreConfig(funding_lookback_days=30),
    )

    assert scores["components"].iloc[0]["funding_zscore"] > 2.0


def test_score_wallet_fills_preserves_infinite_funding_zscore_when_prior_std_is_zero() -> None:
    fills = _fills_frame([_fill(time="2026-05-26T12:00:00Z")])
    funding = pd.DataFrame(
        {"funding_rate": [0.001, 0.001, 0.005]},
        index=pd.to_datetime(
            [
                "2026-05-24T08:00:00Z",
                "2026-05-25T08:00:00Z",
                "2026-05-26T08:00:00Z",
            ],
            utc=True,
        ),
    )

    scores = score_wallet_fills(
        fills,
        _wallet_metrics(),
        {"BTC": funding},
        config=ReverseScoreConfig(),
    )

    assert scores["components"].iloc[0]["funding_zscore"] == math.inf
    assert scores["components"].iloc[0]["funding_extreme_multiplier"] == pytest.approx(
        FUNDING_MAX_BOOST
    )


def test_score_wallet_fills_uses_absolute_notional_for_short_fills() -> None:
    long_scores = score_wallet_fills(
        _fills_frame([_fill(px=100.0, sz=10.0, direction="Open Long")]),
        _wallet_metrics(),
        funding_history={},
        config=ReverseScoreConfig(),
    )
    short_scores = score_wallet_fills(
        _fills_frame([_fill(px=100.0, sz=-10.0, direction="Open Short")]),
        _wallet_metrics(),
        funding_history={},
        config=ReverseScoreConfig(),
    )

    assert short_scores["components"].iloc[0]["risk_ratio"] == pytest.approx(
        long_scores["components"].iloc[0]["risk_ratio"]
    )
    assert short_scores["score"].iloc[0] == pytest.approx(long_scores["score"].iloc[0])


def test_score_wallet_fills_synthesizes_fill_id_for_pd_na() -> None:
    fills = _fills_frame([_fill()])
    fills.loc[0, "fill_id"] = pd.NA

    scores = score_wallet_fills(
        fills,
        _wallet_metrics(),
        funding_history={},
        config=ReverseScoreConfig(),
    )

    assert scores["fill_id"].tolist() == ["fill-1"]


def test_score_wallet_fills_defaults_to_open_fills_only_with_reverse_side() -> None:
    fills = _fills_frame(
        [
            _fill(time="2026-05-26T12:00:00Z", direction="Open Long"),
            {**_fill(time="2026-05-26T13:00:00Z", direction="Close Long"), "fill_id": "fill-2"},
            {**_fill(time="2026-05-26T14:00:00Z", direction="Open Short"), "fill_id": "fill-3"},
            {**_fill(time="2026-05-26T15:00:00Z", direction="Close Short"), "fill_id": "fill-4"},
        ]
    )

    scores = score_wallet_fills(
        fills,
        _wallet_metrics(),
        funding_history={},
        config=ReverseScoreConfig(),
    )

    assert scores["fill_id"].tolist() == ["fill-1", "fill-3"]
    assert scores["dir"].tolist() == ["Open Long", "Open Short"]
    assert scores["reverse_side"].tolist() == ["short", "long"]


def test_score_wallet_fills_can_score_non_open_fills_when_configured() -> None:
    fills = _fills_frame(
        [
            _fill(time="2026-05-26T12:00:00Z", direction="Open Long"),
            {**_fill(time="2026-05-26T13:00:00Z", direction="Close Long"), "fill_id": "fill-2"},
        ]
    )

    scores = score_wallet_fills(
        fills,
        _wallet_metrics(),
        funding_history={},
        config=ReverseScoreConfig(score_open_fills_only=False),
    )

    assert scores["fill_id"].tolist() == ["fill-1", "fill-2"]
    assert scores["reverse_side"].tolist() == ["short", None]


def test_score_wallet_fills_derives_non_eight_hour_funding_settle_interval() -> None:
    fills = _fills_frame([_fill(time="2026-05-26T11:45:00Z")])
    funding = pd.DataFrame(
        {"funding_zscore": [0.0, 0.0, 0.0]},
        index=pd.to_datetime(
            [
                "2026-05-26T00:00:00Z",
                "2026-05-26T06:00:00Z",
                "2026-05-26T12:00:00Z",
            ],
            utc=True,
        ),
    )

    scores = score_wallet_fills(
        fills,
        _wallet_metrics(),
        {"BTC": funding},
        config=ReverseScoreConfig(),
    )

    assert scores["components"].iloc[0]["time_bucket_multiplier"] > 1.0


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"oversized_threshold_1": 0.0}, "oversized_threshold_1"),
        ({"oversized_threshold_1": 0.10, "oversized_threshold_2": 0.05}, "oversized_threshold_2"),
        ({"leverage_threshold_1": 0.0}, "leverage_threshold_1"),
        ({"leverage_threshold_1": 20.0, "leverage_threshold_2": 10.0}, "leverage_threshold_2"),
        ({"funding_z_threshold": 0.0}, "funding_z_threshold"),
        ({"funding_lookback_days": 0}, "funding_lookback_days"),
        ({"asian_session_hours": (-1, 7)}, "asian_session_hours"),
        ({"asian_session_hours": (23, 24)}, "asian_session_hours"),
        ({"funding_settle_minutes_before": -1}, "funding_settle_minutes_before"),
        ({"funding_settle_interval_hours": 0}, "funding_settle_interval_hours"),
        ({"funding_extreme_temperature": 0.0}, "funding_extreme_temperature"),
        ({"time_bucket_temperature": 0.0}, "time_bucket_temperature"),
    ],
)
def test_reverse_score_config_validates_thresholds(kwargs: dict[str, object], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        ReverseScoreConfig(**kwargs)
