"""Funding-rate extreme contrarian signal."""

from __future__ import annotations

import numpy as np
import pandas as pd


def funding_extreme_signal(
    funding_history: dict[str, pd.DataFrame],
    prices: dict[str, pd.Series],
    *,
    z_threshold: float = 2.0,
    lookback_days: int = 30,
    hold_hours: int = 24,
    mean_revert_z: float = 0.5,
    require_min_history: int = 7,
) -> dict[str, tuple[pd.Series, pd.Series, pd.Series]]:
    if z_threshold <= 0:
        raise ValueError("z_threshold must be greater than 0")
    if lookback_days <= 0:
        raise ValueError("lookback_days must be greater than 0")
    if hold_hours <= 0:
        raise ValueError("hold_hours must be greater than 0")
    if mean_revert_z < 0:
        raise ValueError("mean_revert_z must be greater than or equal to 0")
    if require_min_history < 0:
        raise ValueError("require_min_history must be greater than or equal to 0")
    if not funding_history:
        return {}

    result: dict[str, tuple[pd.Series, pd.Series, pd.Series]] = {}
    for symbol, funding in funding_history.items():
        if symbol not in prices:
            continue

        price_index = _price_index(prices[symbol])
        entries = pd.Series(False, index=price_index, dtype=bool)
        exits = pd.Series(False, index=price_index, dtype=bool)
        direction = pd.Series(0, index=price_index, dtype="int64")
        if funding.empty or price_index.empty:
            result[symbol] = (entries, exits, direction)
            continue

        frame = _funding_frame(funding)
        if frame.empty:
            result[symbol] = (entries, exits, direction)
            continue

        z_score = _rolling_zscore(frame["funding_rate"], lookback_days, require_min_history)
        funding_rate = frame["funding_rate"].reindex(price_index, method="ffill")
        aligned_z = z_score.reindex(price_index, method="ffill")
        funding_tick = pd.Series(True, index=frame.index).reindex(price_index, fill_value=False)

        _populate_signals(
            entries,
            exits,
            direction,
            funding_rate,
            aligned_z,
            funding_tick.astype(bool),
            z_threshold,
            pd.Timedelta(hours=hold_hours),
            mean_revert_z,
        )
        result[symbol] = (entries, exits, direction)

    return result


def _populate_signals(
    entries: pd.Series,
    exits: pd.Series,
    direction: pd.Series,
    funding_rate: pd.Series,
    z_score: pd.Series,
    funding_tick: pd.Series,
    z_threshold: float,
    hold_delta: pd.Timedelta,
    mean_revert_z: float,
) -> None:
    active_direction = 0
    entry_time: pd.Timestamp | None = None

    for pos, timestamp in enumerate(entries.index):
        current_z = z_score.iat[pos]
        current_rate = funding_rate.iat[pos]

        if active_direction == 0:
            next_direction = _entry_direction(
                current_rate,
                current_z,
                bool(funding_tick.iat[pos]),
                z_threshold,
            )
            if next_direction == 0:
                continue
            entries.iat[pos] = True
            direction.iat[pos] = next_direction
            active_direction = next_direction
            entry_time = timestamp
            continue

        direction.iat[pos] = active_direction
        hit_hold = entry_time is not None and timestamp >= entry_time + hold_delta
        hit_mean_revert = pd.notna(current_z) and abs(float(current_z)) < mean_revert_z
        if hit_mean_revert or hit_hold:
            exits.iat[pos] = True
            active_direction = 0
            entry_time = None


def _entry_direction(
    funding_rate: float,
    z_score: float,
    is_funding_tick: bool,
    z_threshold: float,
) -> int:
    if not is_funding_tick or pd.isna(funding_rate) or pd.isna(z_score):
        return 0
    if funding_rate > 0 and z_score > z_threshold:
        return -1
    if funding_rate < 0 and z_score < -z_threshold:
        return 1
    return 0


def _rolling_zscore(
    funding_rate: pd.Series,
    lookback_days: int,
    require_min_history: int,
) -> pd.Series:
    previous = funding_rate.shift(1)
    rolling = previous.rolling(f"{lookback_days}D", min_periods=2)
    mean = rolling.mean()
    std = rolling.std(ddof=0)
    diff = funding_rate - mean
    z_score = diff / std

    zero_std = std.eq(0) & mean.notna()
    z_score = z_score.mask(zero_std & diff.gt(0), np.inf)
    z_score = z_score.mask(zero_std & diff.lt(0), -np.inf)
    z_score = z_score.mask(zero_std & diff.eq(0), 0.0)

    min_age = pd.Series(
        funding_rate.index - funding_rate.index[0],
        index=funding_rate.index,
    ) >= pd.Timedelta(days=require_min_history)
    has_observations = rolling.count().ge(2)
    return z_score.where(min_age & has_observations)


def _funding_frame(funding: pd.DataFrame) -> pd.DataFrame:
    if "funding_rate" not in funding.columns:
        return pd.DataFrame(
            {"funding_rate": pd.Series(dtype="float64")},
            index=pd.DatetimeIndex([], name="timestamp", tz="UTC"),
        )

    frame = funding.copy()
    frame.index = _coerce_utc_index(frame.index)
    frame = frame.sort_index()
    frame = frame[~frame.index.duplicated(keep="last")]
    frame["funding_rate"] = pd.to_numeric(frame["funding_rate"], errors="coerce")
    return frame.dropna(subset=["funding_rate"])


def _price_index(prices: pd.Series) -> pd.DatetimeIndex:
    index = _coerce_utc_index(prices.index)
    return pd.DatetimeIndex(index.drop_duplicates().sort_values(), name=prices.index.name)


def _coerce_utc_index(index: pd.Index) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.to_datetime(index, utc=True), name=index.name)
