"""Behavioral bot-wallet fingerprints."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd


BOT_FEATURE_KEYS = (
    "tx_hour_entropy",
    "size_uniformity_cv",
    "coin_diversity",
    "avg_session_gap_minutes",
    "round_number_pct",
)

BOT_SCORE_WEIGHTS = {
    "tx_hour_entropy": 0.20,
    "size_uniformity_cv": 0.25,
    "coin_diversity": 0.20,
    "avg_session_gap_minutes": 0.10,
    "round_number_pct": 0.25,
}


def compute_bot_features(fills: pd.DataFrame, account_value: float) -> dict[str, float]:
    """Compute the five Phase 4 bot fingerprint dimensions."""

    del account_value

    frame = _coerce_fills(fills)
    if frame.empty:
        return _empty_features()

    n_trades = len(frame)
    sizes = _valid_sizes(frame)
    times = frame["time"].dropna().sort_values()

    return {
        "tx_hour_entropy": _hour_entropy(times),
        "size_uniformity_cv": _coefficient_of_variation(sizes),
        "coin_diversity": _coin_diversity(frame, n_trades),
        "avg_session_gap_minutes": _median_gap_minutes(times),
        "round_number_pct": _round_number_pct(sizes),
    }


def score_bot_likelihood(features: dict[str, float]) -> float:
    """Return weighted bot confidence in the closed interval [0, 1]."""

    if not features:
        return 0.0

    score = (
        BOT_SCORE_WEIGHTS["tx_hour_entropy"] * _hour_entropy_score(_feature(features, "tx_hour_entropy"))
        + BOT_SCORE_WEIGHTS["size_uniformity_cv"]
        * _size_uniformity_score(_feature(features, "size_uniformity_cv"))
        + BOT_SCORE_WEIGHTS["coin_diversity"]
        * _coin_concentration_score(_feature(features, "coin_diversity"))
        + BOT_SCORE_WEIGHTS["avg_session_gap_minutes"]
        * _session_gap_score(_feature(features, "avg_session_gap_minutes"))
        + BOT_SCORE_WEIGHTS["round_number_pct"]
        * _round_number_score(_feature(features, "round_number_pct"))
    )
    return _clamp01(score)


def is_bot_wallet(features: dict[str, float], *, threshold: float = 0.5) -> bool:
    """Classify wallets whose weighted bot score meets the confidence threshold."""

    return score_bot_likelihood(features) + 1e-12 >= _clamp01(float(threshold))


def _empty_features() -> dict[str, float]:
    return {key: 0.0 for key in BOT_FEATURE_KEYS}


def _coerce_fills(fills: pd.DataFrame) -> pd.DataFrame:
    if fills.empty:
        return pd.DataFrame({"time": pd.Series(dtype="datetime64[ns, UTC]")})

    frame = fills.copy()
    if isinstance(frame.index, pd.DatetimeIndex):
        times = pd.Series(frame.index)
        frame = frame.reset_index(drop=True)
    elif "time" in frame.columns:
        times = frame["time"].reset_index(drop=True)
        frame = frame.reset_index(drop=True)
    else:
        times = pd.Series(pd.NaT, index=frame.index)
        frame = frame.reset_index(drop=True)

    frame["time"] = pd.to_datetime(times, utc=True, errors="coerce")
    if "sz" in frame.columns:
        frame["sz"] = pd.to_numeric(frame["sz"], errors="coerce")
    else:
        frame["sz"] = pd.Series(math.nan, index=frame.index, dtype="float64")
    if "coin" not in frame.columns:
        frame["coin"] = pd.Series(pd.NA, index=frame.index, dtype="string")

    return frame.sort_values("time", na_position="last").reset_index(drop=True)


def _valid_sizes(frame: pd.DataFrame) -> pd.Series:
    sizes = pd.to_numeric(frame["sz"], errors="coerce").astype("float64")
    return sizes[sizes.map(_is_positive_finite)]


def _hour_entropy(times: pd.Series) -> float:
    if len(times) <= 1:
        return 0.0

    counts = times.dt.hour.value_counts(sort=False).astype("float64")
    probabilities = counts / counts.sum()
    entropy = -float((probabilities * probabilities.map(math.log)).sum())
    return _clamp01(entropy / math.log(24))


def _coefficient_of_variation(values: pd.Series) -> float:
    if values.empty:
        return 0.0
    mean = float(values.mean())
    if mean <= 0:
        return 0.0
    return float(values.std(ddof=0)) / mean


def _coin_diversity(frame: pd.DataFrame, n_trades: int) -> float:
    if n_trades <= 0:
        return 0.0
    coins = frame["coin"].astype("string").dropna()
    if coins.empty:
        return 0.0
    return float(coins.nunique()) / float(n_trades)


def _median_gap_minutes(times: pd.Series) -> float:
    if len(times) <= 1:
        return 0.0
    gaps = times.sort_values().diff().dropna().dt.total_seconds() / 60.0
    if gaps.empty:
        return 0.0
    return float(gaps.median())


def _round_number_pct(sizes: pd.Series) -> float:
    if sizes.empty:
        return 0.0
    return float(sizes.map(_is_round_number_size).mean())


def _is_round_number_size(value: Any) -> bool:
    if not _is_positive_finite(value):
        return False
    size = float(value)
    rounded = round(size)
    if abs(size - rounded) > max(1e-9, abs(size) * 1e-9):
        return False
    return rounded >= 100 and rounded % 100 == 0


def _is_positive_finite(value: Any) -> bool:
    try:
        size = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(size) and size > 0


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _feature(features: dict[str, float], key: str) -> float | None:
    try:
        value = float(features[key])
    except (KeyError, TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return value


def _hour_entropy_score(value: float | None) -> float:
    if value is None:
        return 0.0
    return _linear_score(value, low=0.35, high=0.80)


def _size_uniformity_score(value: float | None) -> float:
    if value is None:
        return 0.0
    return 1.0 - _linear_score(value, low=0.05, high=0.75)


def _coin_concentration_score(value: float | None) -> float:
    if value is None:
        return 0.0
    return 1.0 - _linear_score(value, low=0.20, high=0.80)


def _session_gap_score(value: float | None) -> float:
    if value is None:
        return 0.0
    return 1.0 - _linear_score(value, low=30.0, high=690.0)


def _round_number_score(value: float | None) -> float:
    if value is None:
        return 0.0
    return _linear_score(value, low=0.10, high=0.80)


def _linear_score(value: float, *, low: float, high: float) -> float:
    if high <= low:
        return 0.0
    return _clamp01((value - low) / (high - low))
