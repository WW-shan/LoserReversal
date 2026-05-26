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


def wallet_confidence_weight(wallet_metrics: Any) -> float:
    loss_rate = _numeric(_get_value(wallet_metrics, "realized_loss_rate_90d", 0.0), default=0.0)
    leverage = _numeric(_get_value(wallet_metrics, "leverage_avg_90d", 0.0), default=0.0)
    n_trades = _numeric(_get_value(wallet_metrics, "n_trades_90d", 0.0), default=0.0)

    loss_component = _bounded_linear(loss_rate, low=0.50, high=1.00)
    leverage_component = _bounded_linear(leverage, low=5.0, high=20.0)
    trade_component = _bounded_linear(n_trades, low=50.0, high=200.0)
    return float((loss_component + leverage_component + trade_component) / 3.0)


def score_wallet_fills(
    wallet_fills: pd.DataFrame,
    wallet_metrics: Any,
    funding_history: Any,
    *,
    config: ReverseScoreConfig,
) -> pd.DataFrame:
    if wallet_fills.empty:
        return _empty_score_frame()

    account_value = _numeric(_get_value(wallet_metrics, "account_value", 0.0), default=0.0)
    confidence = wallet_confidence_weight(wallet_metrics)
    rows: list[dict[str, Any]] = []

    frame = wallet_fills.copy()
    if "time" not in frame.columns and isinstance(frame.index, pd.DatetimeIndex):
        frame = frame.reset_index(names="time")
    if "time" in frame.columns:
        frame["time"] = pd.to_datetime(frame["time"], utc=True, errors="coerce")
    if "coin" in frame.columns:
        frame["coin"] = frame["coin"].astype("string")
    if "px" in frame.columns:
        frame["px"] = pd.to_numeric(frame["px"], errors="coerce")
    if "sz" in frame.columns:
        frame["sz"] = pd.to_numeric(frame["sz"], errors="coerce")
    if "leverage" in frame.columns:
        frame["leverage"] = pd.to_numeric(frame["leverage"], errors="coerce")

    for position, row in enumerate(frame.itertuples(index=False), start=0):
        fill = row._asdict()
        fill_id = _fill_id(fill, position)
        coin = _string_value(fill.get("coin"))
        timestamp = _fill_timestamp(fill)
        context = _funding_context_for_fill(coin, timestamp, funding_history)
        components = _score_components(fill, account_value, context, config)
        score = 1.0
        for multiplier in components.values():
            score *= multiplier
        rows.append(
            {
                "fill_id": fill_id,
                "score": float(score),
                "components": {
                    "risk_ratio": _risk_ratio(fill, account_value),
                    "oversized_multiplier": components["oversized"],
                    "leverage_multiplier": components["leverage"],
                    "funding_extreme_multiplier": components["funding_extreme"],
                    "time_bucket_multiplier": components["time_bucket"],
                    "leverage": _numeric(_get_value(fill, "leverage", 0.0), default=0.0),
                    "funding_zscore": _funding_context_value(context),
                    "wallet_confidence": confidence,
                },
            }
        )

    result = pd.DataFrame(rows, columns=["fill_id", "score", "components"])
    result["fill_id"] = result["fill_id"].astype("string")
    result["score"] = pd.to_numeric(result["score"], errors="coerce").astype("float64")
    return result.reset_index(drop=True)


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


def _funding_context_for_fill(
    coin: str | None,
    timestamp: pd.Timestamp | None,
    funding_history: Any,
) -> dict[str, float] | None:
    if not coin or timestamp is None or funding_history is None:
        return None

    frame = _get_value(funding_history, coin, None)
    if frame is None:
        frame = _get_value(funding_history, coin.upper(), None)
    if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
        return None

    normalized = _normalize_funding_frame(frame)
    if normalized.empty:
        return None

    window = normalized.loc[:timestamp]
    if window.empty:
        return None

    for column in ("funding_zscore", "zscore", "z_score"):
        if column in window.columns:
            value = _numeric(window[column].iloc[-1], default=0.0)
            return {"funding_zscore": value}

    if "funding_rate" not in window.columns:
        return None

    rates = pd.to_numeric(window["funding_rate"], errors="coerce").dropna()
    if len(rates) < 2:
        return None

    current = float(rates.iloc[-1])
    history = rates.iloc[:-1]
    if history.empty:
        return None

    mean = float(history.mean())
    std = float(history.std(ddof=0))
    if not math.isfinite(mean) or not math.isfinite(std):
        return None
    if std == 0:
        zscore = 0.0 if current == mean else math.copysign(math.inf, current - mean)
    else:
        zscore = (current - mean) / std
    if not math.isfinite(zscore):
        return None
    return {"funding_zscore": float(zscore)}


def _normalize_funding_frame(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy()
    if not isinstance(normalized.index, pd.DatetimeIndex):
        if "timestamp" in normalized.columns:
            normalized.index = pd.to_datetime(normalized["timestamp"], utc=True, errors="coerce")
        elif "time" in normalized.columns:
            normalized.index = pd.to_datetime(normalized["time"], utc=True, errors="coerce")
        else:
            return pd.DataFrame(index=pd.DatetimeIndex([], tz="UTC"))
    else:
        normalized.index = pd.to_datetime(normalized.index, utc=True, errors="coerce")

    normalized = normalized.loc[normalized.index.notna()].sort_index()
    if normalized.empty:
        return normalized
    normalized = normalized[~normalized.index.duplicated(keep="last")]
    for column in ("funding_rate", "funding_zscore", "zscore", "z_score"):
        if column in normalized.columns:
            normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
    return normalized


def _funding_context_value(context: dict[str, float] | None) -> float:
    if not context:
        return 0.0
    return _numeric(context.get("funding_zscore"), default=0.0)


def _fill_id(fill: Mapping[str, Any] | Any, position: int) -> str:
    for key in ("fill_id", "tid", "oid", "hash"):
        value = _get_value(fill, key, None)
        if value is not None and str(value) != "":
            return str(value)
    return f"fill-{position + 1}"


def _string_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    if not text or text == "<NA>":
        return None
    return text


def _bounded_linear(value: float, *, low: float, high: float) -> float:
    if not math.isfinite(value):
        return 0.0
    if high <= low:
        return 0.0
    return max(0.0, min(1.0, (float(value) - low) / (high - low)))


def _empty_score_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "fill_id": pd.Series(dtype="string"),
            "score": pd.Series(dtype="float64"),
            "components": pd.Series(dtype="object"),
        }
    )


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
