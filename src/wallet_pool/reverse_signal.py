"""Multi-feature reverse-alpha scoring for academic anti-alpha wallet fills."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

import pandas as pd


@dataclass(frozen=True)
class ReverseScoreConfig:
    oversized_threshold_1: float = 0.05
    oversized_threshold_2: float = 0.10
    leverage_threshold_1: float = 10.0
    leverage_threshold_2: float = 20.0
    funding_z_threshold: float = 2.0
    asian_session_hours: tuple[int, int] = (0, 8)
    funding_settle_minutes_before: int = 30


def compute_reverse_alpha_score(
    fill: Any,
    wallet_account_value: float,
    funding_context: Any,
    *,
    config: ReverseScoreConfig,
) -> float:
    score = 1.0
    components = _score_components(fill, wallet_account_value, funding_context, config)
    for multiplier in components.values():
        score *= multiplier
    return float(score)


def _score_components(
    fill: Any,
    wallet_account_value: float,
    funding_context: Any,
    config: ReverseScoreConfig,
) -> dict[str, float]:
    risk_ratio = _risk_ratio(fill, wallet_account_value)
    leverage = _numeric(_get_value(fill, "leverage", 0.0), default=0.0)
    funding_zscore = _funding_zscore(funding_context)
    timestamp = _fill_timestamp(fill)

    oversized = 1.0
    if risk_ratio >= config.oversized_threshold_1:
        oversized *= 1.5
    if risk_ratio >= config.oversized_threshold_2:
        oversized *= 2.0

    leverage_multiplier = 1.0
    if leverage >= config.leverage_threshold_1:
        leverage_multiplier *= 1.3
    if leverage >= config.leverage_threshold_2:
        leverage_multiplier *= 1.6

    funding_extreme = 1.0
    if abs(funding_zscore) >= config.funding_z_threshold:
        funding_extreme *= 1.4

    time_bucket = 1.0
    if timestamp is not None and (
        _is_asian_session(timestamp, config) or _is_funding_settle_window(timestamp, config)
    ):
        time_bucket *= 1.2

    return {
        "oversized": oversized,
        "leverage": leverage_multiplier,
        "funding_extreme": funding_extreme,
        "time_bucket": time_bucket,
    }


def _risk_ratio(fill: Any, wallet_account_value: float) -> float:
    account_value = _numeric(wallet_account_value, default=0.0)
    if account_value <= 0:
        return 0.0

    notional = _numeric(_get_value(fill, "notional", None), default=math.nan)
    if not math.isfinite(notional):
        px = _numeric(_get_value(fill, "px", 0.0), default=0.0)
        sz = _numeric(_get_value(fill, "sz", 0.0), default=0.0)
        notional = px * sz
    if notional <= 0 or not math.isfinite(notional):
        return 0.0
    return notional / account_value


def _funding_zscore(funding_context: Any) -> float:
    if funding_context is None:
        return 0.0
    for key in ("funding_zscore", "funding_z", "zscore", "z_score"):
        value = _get_value(funding_context, key, None)
        if value is not None:
            return _numeric(value, default=0.0)
    return _numeric(funding_context, default=0.0)


def _fill_timestamp(fill: Any) -> pd.Timestamp | None:
    value = _get_value(fill, "time", None)
    if value is None:
        value = _get_value(fill, "timestamp", None)
    if value is None:
        return None

    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        return None
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _is_asian_session(timestamp: pd.Timestamp, config: ReverseScoreConfig) -> bool:
    start_hour, end_hour = config.asian_session_hours
    hour = timestamp.hour
    if start_hour <= end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour


def _is_funding_settle_window(timestamp: pd.Timestamp, config: ReverseScoreConfig) -> bool:
    if config.funding_settle_minutes_before <= 0:
        return False

    minutes_since_day_start = timestamp.hour * 60 + timestamp.minute + timestamp.second / 60
    minutes_since_last_settle = minutes_since_day_start % (8 * 60)
    minutes_until_next_settle = (8 * 60 - minutes_since_last_settle) % (8 * 60)
    return 0 < minutes_until_next_settle <= config.funding_settle_minutes_before


def _get_value(source: Any, key: str, default: Any) -> Any:
    if isinstance(source, Mapping):
        return source.get(key, default)
    try:
        value = source[key]
    except (KeyError, IndexError, TypeError):
        return getattr(source, key, default)
    return value


def _numeric(value: Any, *, default: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(numeric):
        return default
    return numeric
