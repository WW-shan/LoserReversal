"""Behavioral bot-wallet fingerprints.

Weights and thresholds are hand-tuned; labeled-data calibration is deferred to
Phase 4 Slice 3 walkforward.
"""

from __future__ import annotations

import math
import numbers
import warnings
from typing import Any

import pandas as pd


# Five score-relevant feature keys. `n_trades` is tracked outside this tuple because
# it is a gating count, not a scored feature; it is still returned in the same dict
# by `compute_bot_features`.
BOT_FEATURE_KEYS = (
    "tx_hour_entropy",
    "size_uniformity_cv",
    "coin_diversity",
    "median_session_gap_minutes",
    "round_number_pct",
)

# Thresholds derived from ROADMAP Week 11 manual inspection; calibration via
# labeled ground truth deferred to Phase 4 Slice 3 walkforward.
BOT_SCORE_WEIGHTS = {
    "tx_hour_entropy": 0.20,
    "size_uniformity_cv": 0.25,
    "coin_diversity": 0.20,
    "median_session_gap_minutes": 0.10,
    "round_number_pct": 0.25,
}


def compute_bot_features(fills: pd.DataFrame, **legacy_kwargs: Any) -> dict[str, float]:
    """Compute Phase 4 bot fingerprints plus n_trades for the score-gating contract.

    Accepts (and deprecates) `account_value` as a legacy keyword for backward compat
    with the prior signature; `scripts/build_clean_wallet_pool.py` was updated to drop
    this argument as part of the same slice. Any other keyword raises TypeError.
    """

    if "account_value" in legacy_kwargs:
        warnings.warn(
            "account_value is deprecated and ignored; remove from call sites",
            DeprecationWarning,
            stacklevel=2,
        )
        legacy_kwargs.pop("account_value")
    if legacy_kwargs:
        unexpected = sorted(legacy_kwargs)[0]
        raise TypeError(f"compute_bot_features() got an unexpected keyword argument '{unexpected}'")

    frame = _coerce_fills(fills)
    if frame.empty:
        return _empty_features()

    n_trades = len(frame)
    notionals = _notional_values(frame)
    valid_notionals = notionals[notionals.map(_is_positive_finite)]
    times = frame["time"].dropna().sort_values()

    return {
        "tx_hour_entropy": _hour_entropy(times),
        "size_uniformity_cv": _coefficient_of_variation(valid_notionals),
        "coin_diversity": _coin_diversity(frame, n_trades),
        "median_session_gap_minutes": _median_gap_minutes(times),
        "round_number_pct": _round_number_pct(notionals, n_trades),
        "n_trades": float(n_trades),
    }


def score_bot_likelihood(
    features: dict[str, float],
    *,
    min_trades_for_scoring: int = 10,
) -> float:
    """Return weighted bot confidence in the closed interval [0, 1].

    Wallets with `n_trades < min_trades_for_scoring` return 0.0 unconditionally;
    caller MUST surface this to avoid scoring on insufficient data.
    """

    if min_trades_for_scoring < 1:
        raise ValueError(
            f"min_trades_for_scoring must be >= 1, got {min_trades_for_scoring}"
        )
    if not features:
        return 0.0
    if "n_trades" not in features:
        raise ValueError(
            "features dict missing required 'n_trades' key (was the dict produced by "
            "compute_bot_features?). Either include n_trades or pass an empty dict."
        )
    n_trades = _feature(features, "n_trades")
    if n_trades is None or n_trades < min_trades_for_scoring:
        return 0.0

    score = (
        BOT_SCORE_WEIGHTS["tx_hour_entropy"] * _hour_entropy_score(_feature(features, "tx_hour_entropy"))
        + BOT_SCORE_WEIGHTS["size_uniformity_cv"]
        * _size_uniformity_score(_feature(features, "size_uniformity_cv"))
        + BOT_SCORE_WEIGHTS["coin_diversity"]
        * _coin_concentration_score(_feature(features, "coin_diversity"))
        + BOT_SCORE_WEIGHTS["median_session_gap_minutes"]
        * _session_gap_score(_feature(features, "median_session_gap_minutes"))
        + BOT_SCORE_WEIGHTS["round_number_pct"]
        * _round_number_score(_feature(features, "round_number_pct"))
    )
    return _clamp01(score)


def is_bot_wallet(
    features: dict[str, float],
    *,
    threshold: float = 0.5,
    min_trades_for_scoring: int = 10,
) -> bool:
    """Classify wallets whose weighted bot score meets the confidence threshold.

    Raises ValueError if threshold is outside [0, 1] or if min_trades_for_scoring < 1.
    """

    if min_trades_for_scoring < 1:
        raise ValueError(
            f"min_trades_for_scoring must be >= 1, got {min_trades_for_scoring}"
        )
    threshold_value = float(threshold)
    if not 0.0 <= threshold_value <= 1.0:
        raise ValueError(f"threshold must be in [0, 1], got {threshold}")
    return score_bot_likelihood(
        features,
        min_trades_for_scoring=min_trades_for_scoring,
    ) >= threshold_value


def _empty_features() -> dict[str, float]:
    features = {key: 0.0 for key in BOT_FEATURE_KEYS}
    features["n_trades"] = 0.0
    return features


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
    if "px" in frame.columns:
        frame["px"] = pd.to_numeric(frame["px"], errors="coerce")
    else:
        frame["px"] = pd.Series(math.nan, index=frame.index, dtype="float64")
    if "coin" not in frame.columns:
        frame["coin"] = pd.Series(pd.NA, index=frame.index, dtype="string")

    return frame.sort_values("time", na_position="last").reset_index(drop=True)


def _notional_values(frame: pd.DataFrame) -> pd.Series:
    prices = pd.to_numeric(frame["px"], errors="coerce").astype("float64")
    sizes = pd.to_numeric(frame["sz"], errors="coerce").astype("float64")
    return (prices * sizes).abs()


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
    if not math.isfinite(mean) or mean <= 0:
        return 0.0
    # ddof=0 is intentional; population std is robust at small samples since we don't
    # assume Gaussian. At n_trades=10 (default min_trades_for_scoring), ddof=0 vs ddof=1
    # differ by ~5% (factor sqrt(n/(n-1))=sqrt(10/9)).
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


def _round_number_pct(notionals: pd.Series, n_trades: int) -> float:
    """Fraction of all n_trades whose USD notional is a positive integer multiple of $100 (>= $100).

    Non-positive/non-finite notionals score False, retaining n_trades as denominator.
    """

    if n_trades <= 0:
        return 0.0
    return float(pd.to_numeric(notionals, errors="coerce").map(_is_round_number_notional).mean())


def _is_round_number_notional(value: Any) -> bool:
    if not _is_positive_finite(value):
        return False
    notional = float(value)
    rounded = round(notional)
    if abs(notional - rounded) > max(1e-9, abs(notional) * 1e-9):
        return False
    return rounded >= 100 and rounded % 100 == 0


def _is_positive_finite(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if not isinstance(value, numbers.Real):
        return False
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
