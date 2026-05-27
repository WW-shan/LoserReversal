"""Per-signal BTC trend-regime filter.

Each signal in SIGNAL_REGISTRY has its own entry_offset_days and direction
("short" or "long"). This filter gates events at each signal's entry
timestamp (unlock_date + entry_offset_days) against BTC's 200d SMA trend:
- direction="short": keep events landing in bear regime (BTC < SMA)
- direction="long": keep events landing in bull regime (BTC >= SMA)

Phase 1.5 diagnostic identified Split 4 (bear period 2025-09 to 2026-03)
as punishing naive unlock shorts; this filter excludes events outside
the trend favoring the signal's direction.
"""

from __future__ import annotations

import pandas as pd


DEFAULT_WINDOW = 200


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
