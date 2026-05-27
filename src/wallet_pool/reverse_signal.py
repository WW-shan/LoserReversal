"""Multi-feature reverse-alpha scoring for academic anti-alpha wallet fills."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

import pandas as pd

DEFAULT_FUNDING_SETTLE_INTERVAL_HOURS = 8.0
OPEN_DIRECTIONS = frozenset({"Open Long", "Open Short"})
CLOSE_DIRECTIONS = frozenset({"Close Long", "Close Short"})
ACTIONABLE_DIRECTIONS = OPEN_DIRECTIONS | CLOSE_DIRECTIONS


@dataclass(frozen=True)
class ReverseScoreConfig:
    """Controls reverse-alpha score thresholds and smooth boost parameters.

    Funding extremes use a logistic boost centered at ``funding_z_threshold``.
    Timing uses the same normalized boost over Tokyo-open session membership
    (default 23:00-07:00 UTC, per the Asia liquidity handoff notes in
    ``docs/research/literature-review.md``) and proximity to the next funding
    settle. ``funding_settle_interval_hours`` defaults to auto-detect from
    funding history and falls back to 8 hours.
    """

    oversized_threshold_1: float = 0.05
    oversized_threshold_2: float = 0.10
    leverage_threshold_1: float = 10.0
    leverage_threshold_2: float = 20.0
    funding_z_threshold: float = 2.0
    funding_lookback_days: int = 30
    asian_session_hours: tuple[int, int] = (23, 7)
    funding_settle_minutes_before: int = 30
    funding_settle_interval_hours: float | None = None
    score_open_fills_only: bool = True
    funding_extreme_max_boost: float = 1.4
    funding_extreme_temperature: float = 0.5
    time_bucket_max_boost: float = 1.2
    time_bucket_pivot: float = 0.5
    time_bucket_temperature: float = 0.2

    def __post_init__(self) -> None:
        _validate_positive("oversized_threshold_1", self.oversized_threshold_1)
        _validate_positive("oversized_threshold_2", self.oversized_threshold_2)
        if self.oversized_threshold_2 < self.oversized_threshold_1:
            raise ValueError("oversized_threshold_2 must be >= oversized_threshold_1")
        _validate_positive("leverage_threshold_1", self.leverage_threshold_1)
        _validate_positive("leverage_threshold_2", self.leverage_threshold_2)
        if self.leverage_threshold_2 < self.leverage_threshold_1:
            raise ValueError("leverage_threshold_2 must be >= leverage_threshold_1")
        _validate_positive("funding_z_threshold", self.funding_z_threshold)
        _validate_positive_int("funding_lookback_days", self.funding_lookback_days)
        _validate_session_hours(self.asian_session_hours)
        if self.funding_settle_minutes_before < 0:
            raise ValueError("funding_settle_minutes_before must be >= 0")
        if self.funding_settle_interval_hours is not None:
            _validate_positive("funding_settle_interval_hours", self.funding_settle_interval_hours)
        _validate_minimum("funding_extreme_max_boost", self.funding_extreme_max_boost, minimum=1.0)
        _validate_positive("funding_extreme_temperature", self.funding_extreme_temperature)
        _validate_minimum("time_bucket_max_boost", self.time_bucket_max_boost, minimum=1.0)
        if not 0.0 <= self.time_bucket_pivot <= 1.0:
            raise ValueError("time_bucket_pivot must be between 0 and 1")
        _validate_positive("time_bucket_temperature", self.time_bucket_temperature)


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
    """Return wallet-level confidence with log-scaled trade-count dispersion.

    The academic pool has n_trades ranging from low hundreds to thousands, so
    log1p keeps 200-trade and 5,000-trade wallets distinguishable without
    letting the largest wallets dominate the confidence weight.
    """

    loss_rate = _numeric(_get_value(wallet_metrics, "realized_loss_rate_90d", 0.0), default=0.0)
    leverage = _numeric(_get_value(wallet_metrics, "leverage_avg_90d", 0.0), default=0.0)
    n_trades = _numeric(_get_value(wallet_metrics, "n_trades_90d", 0.0), default=0.0)

    loss_component = _bounded_linear(loss_rate, low=0.50, high=1.00)
    leverage_component = _bounded_linear(leverage, low=5.0, high=20.0)
    trade_signal = math.log1p(n_trades) if n_trades > 0 else 0.0
    trade_component = _bounded_linear(
        trade_signal,
        low=math.log1p(50.0),
        high=math.log1p(5000.0),
    )
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
    if "dir" in frame.columns:
        frame["dir"] = frame["dir"].astype("string")

    if "dir" not in frame.columns:
        return _empty_score_frame()
    scorable_directions = OPEN_DIRECTIONS if config.score_open_fills_only else ACTIONABLE_DIRECTIONS
    frame = frame.loc[frame["dir"].isin(scorable_directions)].copy()
    if frame.empty:
        return _empty_score_frame()

    for position, row in enumerate(frame.itertuples(index=False), start=0):
        fill = row._asdict()
        fill_id = _fill_id(fill, position)
        coin = _string_value(fill.get("coin"))
        timestamp = _fill_timestamp(fill)
        direction = _string_value(fill.get("dir"))
        context = _funding_context_for_fill(coin, timestamp, funding_history, config)
        components = _score_components(fill, account_value, context, config)
        score = 1.0
        for multiplier in components.values():
            score *= multiplier
        rows.append(
            {
                "fill_id": fill_id,
                "time": timestamp,
                "dir": direction,
                "reverse_side": _reverse_side(direction),
                "token": coin or "",
                "score": float(score),
                "components": {
                    "risk_ratio": _risk_ratio(fill, account_value),
                    "oversized_multiplier": components["oversized"],
                    "leverage_multiplier": components["leverage"],
                    "funding_extreme_multiplier": components["funding_extreme"],
                    "time_bucket_multiplier": components["time_bucket"],
                    "leverage": _fill_leverage(fill, account_value),
                    "funding_zscore": _funding_context_value(context),
                    "wallet_confidence": confidence,
                },
            }
        )

    result = pd.DataFrame(
        rows,
        columns=["fill_id", "time", "dir", "reverse_side", "token", "score", "components"],
    )
    result["fill_id"] = result["fill_id"].astype("string")
    result["time"] = pd.to_datetime(result["time"], utc=True, errors="coerce")
    result["dir"] = result["dir"].astype("string")
    result["reverse_side"] = result["reverse_side"].astype(object)
    result.loc[result["reverse_side"].isna(), "reverse_side"] = None
    result["token"] = result["token"].astype("string")
    result["score"] = pd.to_numeric(result["score"], errors="coerce").astype("float64")
    return result.reset_index(drop=True)


def _score_components(
    fill: Any,
    wallet_account_value: float,
    funding_context: Any,
    config: ReverseScoreConfig,
) -> dict[str, float]:
    risk_ratio = _risk_ratio(fill, wallet_account_value)
    leverage = _fill_leverage(fill, wallet_account_value)
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

    funding_extreme = _funding_extreme_multiplier(funding_zscore, config)

    time_bucket = _time_bucket_multiplier(timestamp, funding_context, config)

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
    notional = abs(notional)
    if notional <= 0 or not math.isfinite(notional):
        return 0.0
    return notional / account_value


def _funding_zscore(funding_context: Any) -> float:
    """Return finite or infinite z-score; infinities encode zero-std shocks."""

    if funding_context is None:
        return 0.0
    for key in ("funding_zscore", "funding_z", "zscore", "z_score"):
        value = _get_value(funding_context, key, None)
        if value is not None:
            return _funding_numeric(value, default=0.0)
    return _funding_numeric(funding_context, default=0.0)


def _fill_leverage(fill: Any, wallet_account_value: float) -> float:
    value = _get_value(fill, "leverage", None)
    leverage = _numeric(value, default=math.nan)
    if math.isfinite(leverage) and leverage > 0:
        return leverage
    return _risk_ratio(fill, wallet_account_value)


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
    config: ReverseScoreConfig,
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

    interval_hours = _funding_settle_interval_hours(normalized, config)
    context: dict[str, float] = {}
    if interval_hours is not None:
        context["funding_settle_interval_hours"] = interval_hours

    window = normalized.loc[normalized.index < timestamp]
    if window.empty:
        return context or None

    for column in ("funding_zscore", "zscore", "z_score"):
        if column in window.columns:
            series = pd.to_numeric(window[column], errors="coerce").dropna()
            if not series.empty:
                return {**context, "funding_zscore": float(series.iloc[-1])}

    if "funding_rate" not in window.columns:
        return context or None

    rates = pd.to_numeric(window["funding_rate"], errors="coerce").dropna()
    zscore = _rolling_funding_zscore(rates, config)
    if zscore is None:
        return context or None
    return {**context, "funding_zscore": zscore}


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
    return _funding_numeric(context.get("funding_zscore"), default=0.0)


def _fill_id(fill: Mapping[str, Any] | Any, position: int) -> str:
    for key in ("fill_id", "tid", "oid", "hash"):
        value = _get_value(fill, key, None)
        text = _string_value(value)
        if text is not None:
            return text
    return f"fill-{position + 1}"


def _string_value(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
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
            "time": pd.Series(dtype="datetime64[ns, UTC]"),
            "dir": pd.Series(dtype="string"),
            "reverse_side": pd.Series(dtype="object"),
            "token": pd.Series(dtype="string"),
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


def _is_funding_settle_window(
    timestamp: pd.Timestamp,
    config: ReverseScoreConfig,
    funding_context: Any = None,
) -> bool:
    return _funding_settle_signal(timestamp, config, funding_context) > 0.0


def _reverse_side(direction: str | None) -> str | None:
    if direction in ("Open Long", "Close Short"):
        return "short"
    if direction in ("Open Short", "Close Long"):
        return "long"
    return None


def _funding_extreme_multiplier(zscore: float, config: ReverseScoreConfig) -> float:
    magnitude = abs(zscore)
    if not math.isfinite(magnitude):
        return config.funding_extreme_max_boost if math.isinf(magnitude) else 1.0
    return _smooth_boost(
        magnitude,
        max_boost=config.funding_extreme_max_boost,
        pivot=config.funding_z_threshold,
        temperature=config.funding_extreme_temperature,
    )


def _time_bucket_multiplier(
    timestamp: pd.Timestamp | None,
    funding_context: Any,
    config: ReverseScoreConfig,
) -> float:
    if timestamp is None:
        return 1.0
    signal = 0.0
    if _is_asian_session(timestamp, config):
        signal = 1.0
    signal = max(signal, _funding_settle_signal(timestamp, config, funding_context))
    return _smooth_boost(
        signal,
        max_boost=config.time_bucket_max_boost,
        pivot=config.time_bucket_pivot,
        temperature=config.time_bucket_temperature,
    )


def _funding_settle_signal(
    timestamp: pd.Timestamp,
    config: ReverseScoreConfig,
    funding_context: Any = None,
) -> float:
    if config.funding_settle_minutes_before <= 0:
        return 0.0

    interval_hours = _context_interval_hours(funding_context, config)
    interval_minutes = interval_hours * 60.0
    minutes_since_day_start = timestamp.hour * 60 + timestamp.minute + timestamp.second / 60
    minutes_since_last_settle = minutes_since_day_start % interval_minutes
    minutes_until_next_settle = (interval_minutes - minutes_since_last_settle) % interval_minutes
    if not 0 < minutes_until_next_settle <= config.funding_settle_minutes_before:
        return 0.0
    return max(0.0, min(1.0, 1.0 - minutes_until_next_settle / config.funding_settle_minutes_before))


def _smooth_boost(
    signal: float,
    *,
    max_boost: float,
    pivot: float,
    temperature: float,
) -> float:
    return 1.0 + (max_boost - 1.0) * _sigmoid((signal - pivot) / temperature)


def _sigmoid(value: float) -> float:
    if value >= 0:
        scaled = math.exp(-value)
        return 1.0 / (1.0 + scaled)
    scaled = math.exp(value)
    return scaled / (1.0 + scaled)


def _rolling_funding_zscore(rates: pd.Series, config: ReverseScoreConfig) -> float | None:
    if len(rates) < 3:
        return None

    previous = rates.shift(1)
    rolling = previous.rolling(f"{config.funding_lookback_days}D", min_periods=2)
    mean = rolling.mean()
    std = rolling.std(ddof=0)

    current = float(rates.iloc[-1])
    current_mean = float(mean.iloc[-1])
    current_std = float(std.iloc[-1])
    if math.isnan(current_mean) or math.isnan(current_std):
        return None
    diff = current - current_mean
    if current_std == 0:
        zscore = 0.0 if diff == 0 else math.copysign(math.inf, diff)
    else:
        zscore = diff / current_std
    if math.isnan(zscore):
        return None
    return float(zscore)


def _funding_settle_interval_hours(
    normalized: pd.DataFrame,
    config: ReverseScoreConfig,
) -> float | None:
    if config.funding_settle_interval_hours is not None:
        return float(config.funding_settle_interval_hours)
    if len(normalized.index) < 2:
        return None
    deltas = normalized.index.to_series().diff().dropna().dt.total_seconds()
    if deltas.empty:
        return None
    seconds = float(deltas.median())
    if not math.isfinite(seconds) or seconds <= 0:
        return None
    return seconds / 3600.0


def _context_interval_hours(funding_context: Any, config: ReverseScoreConfig) -> float:
    if config.funding_settle_interval_hours is not None:
        return float(config.funding_settle_interval_hours)
    interval = _numeric(
        _get_value(funding_context, "funding_settle_interval_hours", None),
        default=math.nan,
    )
    if math.isfinite(interval) and interval > 0:
        return interval
    return DEFAULT_FUNDING_SETTLE_INTERVAL_HOURS


def _validate_positive(name: str, value: float) -> None:
    if not math.isfinite(float(value)) or float(value) <= 0:
        raise ValueError(f"{name} must be positive")


def _validate_positive_int(name: str, value: int) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _validate_minimum(name: str, value: float, *, minimum: float) -> None:
    if not math.isfinite(float(value)) or float(value) < minimum:
        raise ValueError(f"{name} must be >= {minimum}")


def _validate_session_hours(hours: tuple[int, int]) -> None:
    if len(hours) != 2:
        raise ValueError("asian_session_hours must contain start and end hours")
    for hour in hours:
        if int(hour) != hour or hour < 0 or hour >= 24:
            raise ValueError("asian_session_hours values must be integers in [0, 24)")


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


def _funding_numeric(value: Any, *, default: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(numeric):
        return default
    return numeric
