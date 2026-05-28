"""Per-signal trend-regime filters for unlock walkforward.

Each signal in SIGNAL_REGISTRY has its own entry_offset_days and direction
("short" or "long"). The filter gates events at each signal's entry
timestamp (unlock_date + entry_offset_days) against the chosen regime.

Two regime detectors:

1. ``compute_btc_regime`` — BTC < N-day SMA classifier. Original Phase 1.5
   design. direction="short" keeps events landing in bear (BTC < SMA);
   direction="long" keeps events landing in bull (BTC >= SMA). Phase 1.5
   diagnostic identified Split 4 (bear period 2025-09 → 2026-03) as
   punishing naive unlock shorts; this filter excludes events outside
   the trend favoring the signal's direction.

2. ``compute_funding_regime`` — overheated-long classifier based on
   percentile of cross-major rolling-mean funding (2026-05-28 addition).
   direction="short" keeps events landing in bear regime, here meaning
   funding is in the top quartile of in-sample observations (overheated
   long positioning → contrarian short entry). direction="long" keeps
   events in bull regime (below threshold). Useful when BTC 1d candle
   history is too short for 200-day SMA but funding history is longer.

Per smart-search 2026-05-27, extreme positive funding signals overheated
long positioning → contrarian short opportunity. HL funding is ~87%
positive-biased so an absolute funding<0 threshold is too restrictive;
percentile-relative is the right semantic.
"""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd


DEFAULT_WINDOW = 200
DEFAULT_FUNDING_WINDOW_DAYS = 7
DEFAULT_FUNDING_MAJORS: tuple[str, ...] = ("BTC", "ETH")


def compute_btc_regime(
    btc_close: pd.Series,
    *,
    window: int = DEFAULT_WINDOW,
) -> pd.Series:
    """Return a daily bool series: True iff BTC close < N-day SMA (bear regime).

    The input series may be hourly or daily; it gets resampled to daily
    last value before computing the SMA so the regime label is stable
    intra-day. The output index is daily UTC timestamps and the bool is
    True iff that day's close is below the N-day trailing SMA.
    """
    if btc_close.empty:
        return pd.Series(dtype=bool, name="bear")
    if window <= 0:
        raise ValueError("window must be greater than 0")

    daily = _to_daily(btc_close).dropna()
    if daily.empty:
        return pd.Series(dtype=bool, name="bear")

    sma = daily.rolling(window=window, min_periods=window).mean()
    bear = (daily < sma).astype("boolean")
    bear[sma.isna()] = pd.NA
    bear.name = "bear"
    return bear


def is_bear_at(regime: pd.Series, when: pd.Timestamp) -> bool | None:
    """Return the bear flag at or before the given timestamp.

    Returns None when no SMA-warmed observation exists at or before `when`
    (e.g., the lookback window has not yet filled). Callers should treat
    None as "cannot gate — pass through" rather than "bear=False".
    """
    if regime.empty:
        return None
    target_day = _normalize_to_utc(when)
    eligible = regime.loc[regime.index <= target_day]
    eligible = eligible.dropna()
    if eligible.empty:
        return None
    return bool(eligible.iloc[-1])


def filter_events_by_regime(
    events: pd.DataFrame,
    regime: pd.Series,
    *,
    direction: str = "short",
    pass_through_when_unknown: bool = False,
    entry_date_column: str = "unlock_date",
) -> pd.DataFrame:
    """Drop events whose entry timestamp lands outside the regime favouring `direction`.

    direction="short" keeps events landing in bear regime (BTC < SMA).
    direction="long" keeps events landing in bull regime (BTC >= SMA).
    direction="both" returns events unchanged.

    When the regime is unknown at an event's entry timestamp (lookback not yet
    warmed), the event is dropped unless pass_through_when_unknown=True.
    """
    if direction not in {"short", "long", "both"}:
        raise ValueError(f"unsupported direction: {direction}")
    if events.empty or direction == "both":
        return events.copy()
    if entry_date_column not in events.columns:
        return events.copy()

    target = True if direction == "short" else False
    keep_mask = pd.Series(False, index=events.index, dtype=bool)
    # O(n log m); current Phase 1.5 scale is ~1.8k events over ~1k regime days.
    for idx, entry_ts in events[entry_date_column].items():
        try:
            ts = pd.Timestamp(entry_ts)
        except (TypeError, ValueError):
            continue
        bear = is_bear_at(regime, ts)
        if bear is None:
            if pass_through_when_unknown:
                keep_mask.loc[idx] = True
            continue
        keep_mask.loc[idx] = bear == target

    filtered = events.loc[keep_mask].copy()
    return filtered.reset_index(drop=True)


def apply_btc_regime_filter(
    events: pd.DataFrame,
    *,
    btc_close: pd.Series,
    signal_offset_days: int,
    direction: str = "short",
) -> pd.DataFrame:
    """Filter by BTC regime at each event's signal-specific entry date.

    Drops events whose signal-specific entry date
    (unlock_date + signal_offset_days) is in a non-target BTC regime, or in
    the SMA warmup period. Uses prior closes only through the entry date.
    """
    if events.empty or "unlock_date" not in events.columns:
        return events.copy()

    events_with_entry = events.copy()
    unlock_date = pd.to_datetime(events_with_entry["unlock_date"], utc=True, errors="coerce")
    entry_date_column = "__regime_entry_date"
    events_with_entry[entry_date_column] = unlock_date + pd.to_timedelta(
        signal_offset_days,
        unit="D",
    )
    regime = compute_btc_regime(btc_close, window=DEFAULT_WINDOW)
    filtered = filter_events_by_regime(
        events_with_entry,
        regime,
        direction=direction,
        pass_through_when_unknown=False,
        entry_date_column=entry_date_column,
    )
    return filtered.drop(columns=[entry_date_column], errors="ignore")


def compute_funding_regime(
    funding_by_token: Mapping[str, pd.DataFrame],
    *,
    majors: tuple[str, ...] = DEFAULT_FUNDING_MAJORS,
    window_days: int = DEFAULT_FUNDING_WINDOW_DAYS,
    bear_quantile: float = 0.75,
    threshold_min_prior_days: int = 30,
) -> pd.Series:
    """Return a daily bool series: True iff cross-majors rolling mean funding above
    its EXPANDING PRIOR-WINDOW ``bear_quantile`` percentile (overheated long positioning).

    Per smart-search 2026-05-27: extreme positive funding signals overheated
    long positioning → contrarian short opportunity. ``bear_quantile=0.75`` keeps
    only the top quartile of historical funding observations as "bear" regime
    for short-signal entries.

    For each major token, compute the rolling N-day mean funding rate, then
    average across tokens (equal weight). At each day T, the bear-classification
    threshold is the ``bear_quantile`` of warmed observations with index < T
    (strict-less-than, NOT the full sample). This is point-in-time correct:
    the regime label at T uses only funding history strictly before T.

    ``threshold_min_prior_days`` is the minimum number of warmed observations
    required before a non-NA regime label can be produced (fail closed during
    burn-in).

    Per spec rule "Time-series boundary slicing must be strict-less-than":
    historical regime labels never depend on future funding observations.
    """
    if window_days <= 0:
        raise ValueError("window_days must be greater than 0")
    if not majors:
        raise ValueError("majors must contain at least one token")
    if not 0.0 < bear_quantile < 1.0:
        raise ValueError(
            f"bear_quantile must be in (0.0, 1.0); got {bear_quantile!r}"
        )
    if type(threshold_min_prior_days) is not int or threshold_min_prior_days < 1:
        raise ValueError(
            f"threshold_min_prior_days must be a positive int; got "
            f"{threshold_min_prior_days!r}"
        )

    daily_means: list[pd.Series] = []
    for token in majors:
        frame = funding_by_token.get(token)
        if frame is None or frame.empty:
            continue
        if "timestamp" not in frame.columns or "funding_rate" not in frame.columns:
            continue
        ts = pd.to_datetime(frame["timestamp"], utc=True)
        series = pd.Series(
            frame["funding_rate"].to_numpy(), index=pd.DatetimeIndex(ts), dtype="float64"
        )
        daily = series.resample("1D").mean().dropna()
        if daily.empty:
            continue
        roll = daily.rolling(window=window_days, min_periods=window_days).mean()
        roll.name = token
        daily_means.append(roll)

    if not daily_means:
        return pd.Series(dtype=bool, name="bear")

    combined = pd.concat(daily_means, axis=1).mean(axis=1, skipna=True)
    warmed = combined.dropna()
    if warmed.empty:
        return pd.Series(dtype=bool, name="bear")

    # Expanding prior-window quantile (point-in-time correct).
    # At each warmed index T, threshold(T) = quantile of warmed observations with
    # index strictly less than T. Use shift(1) to enforce strict-less-than.
    thresholds = (
        warmed.expanding(min_periods=threshold_min_prior_days)
        .quantile(bear_quantile)
        .shift(1)
    )
    bear = pd.Series(pd.NA, index=combined.index, dtype="boolean", name="bear")
    aligned_thresholds = thresholds.reindex(combined.index)
    mask = combined.notna() & aligned_thresholds.notna()
    bear.loc[mask] = combined.loc[mask] >= aligned_thresholds.loc[mask]
    return bear


def apply_funding_regime_filter(
    events: pd.DataFrame,
    *,
    funding_by_token: Mapping[str, pd.DataFrame],
    signal_offset_days: int,
    direction: str = "short",
    majors: tuple[str, ...] = DEFAULT_FUNDING_MAJORS,
    window_days: int = DEFAULT_FUNDING_WINDOW_DAYS,
    bear_quantile: float = 0.75,
    threshold_min_prior_days: int = 30,
) -> pd.DataFrame:
    """Filter events using funding-rate regime instead of BTC SMA.

    Direction semantics (matching compute_funding_regime):
    - direction="short": keep events landing in bear regime (overheated long
      positioning — aggregate funding above the ``bear_quantile`` percentile)
    - direction="long": keep events landing in bull regime (below the
      threshold, including outright negative funding)

    Per smart-search 2026-05-27: HL funding is ~87% positive-biased so the
    semantic is overheated-long ≡ bear (ripe for reversal down), NOT
    "funding < 0 = bear". An absolute zero threshold would be too restrictive.
    """
    if events.empty or "unlock_date" not in events.columns:
        return events.copy()

    regime = compute_funding_regime(
        funding_by_token,
        majors=majors,
        window_days=window_days,
        bear_quantile=bear_quantile,
        threshold_min_prior_days=threshold_min_prior_days,
    )
    events_with_entry = events.copy()
    unlock_date = pd.to_datetime(events_with_entry["unlock_date"], utc=True, errors="coerce")
    entry_date_column = "__regime_entry_date"
    events_with_entry[entry_date_column] = unlock_date + pd.to_timedelta(
        signal_offset_days,
        unit="D",
    )
    filtered = filter_events_by_regime(
        events_with_entry,
        regime,
        direction=direction,
        pass_through_when_unknown=False,
        entry_date_column=entry_date_column,
    )
    return filtered.drop(columns=[entry_date_column], errors="ignore")


def _to_daily(series: pd.Series) -> pd.Series:
    index = series.index
    if not isinstance(index, pd.DatetimeIndex):
        index = pd.DatetimeIndex(pd.to_datetime(index, utc=True))
    if index.tz is None:
        index = index.tz_localize("UTC")
    else:
        index = index.tz_convert("UTC")
    aligned = pd.Series(series.values, index=index, dtype="float64")
    return aligned.resample("1D").last()


def _normalize_to_utc(ts: pd.Timestamp) -> pd.Timestamp:
    timestamp = pd.Timestamp(ts)
    if timestamp.tz is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.normalize()
