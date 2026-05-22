from __future__ import annotations

import pandas as pd


def unlock_short_signal(
    events: pd.DataFrame,
    prices: dict[str, pd.Series],
    pre_window_days: int = 7,
    min_unlock_pct: float = 0.02,
    require_hl_perp: bool = True,
) -> dict[str, tuple[pd.Series, pd.Series]]:
    if pre_window_days < 1:
        raise ValueError("pre_window_days must be at least 1")
    if events.empty or not prices:
        return {}
    if not {"token", "unlock_date", "unlock_pct"}.issubset(events.columns):
        return {}
    if require_hl_perp and "has_hl_perp" not in events.columns:
        return {}

    frame = events.copy()
    frame["unlock_date"] = pd.to_datetime(frame["unlock_date"], utc=True, errors="coerce")
    frame["unlock_pct"] = pd.to_numeric(frame["unlock_pct"], errors="coerce")
    frame = frame.dropna(subset=["token", "unlock_date"])

    mask = frame["unlock_pct"] >= float(min_unlock_pct)
    if require_hl_perp:
        mask &= _coerce_bool_series(frame["has_hl_perp"])
    frame = frame.loc[mask].copy()
    if frame.empty:
        return {}

    frame["token"] = frame["token"].astype("string")
    frame = frame.sort_values(["token", "unlock_date"])

    result: dict[str, tuple[pd.Series, pd.Series]] = {}
    for token, token_events in frame.groupby("token", sort=False):
        token_name = str(token)
        if token_name not in prices:
            continue

        price_index = pd.DatetimeIndex(prices[token_name].index)
        if price_index.tz is None:
            close_index = pd.DatetimeIndex(price_index, tz="UTC")
        else:
            close_index = price_index.tz_convert("UTC")
        if close_index.empty:
            continue

        entries = pd.Series(False, index=close_index, dtype=bool)
        exits = pd.Series(False, index=close_index, dtype=bool)
        last_exit: pd.Timestamp | None = None

        for unlock_ts in token_events["unlock_date"]:
            entry_ts = unlock_ts - pd.Timedelta(days=pre_window_days)
            if entry_ts not in close_index or unlock_ts not in close_index:
                continue
            if last_exit is not None and entry_ts < last_exit:
                continue

            entries.loc[entry_ts] = True
            exits.loc[unlock_ts] = True
            last_exit = unlock_ts

        if entries.any():
            result[token_name] = (entries, exits)

    return result


def _coerce_bool_series(series: pd.Series) -> pd.Series:
    return series.astype("string").str.lower().isin({"true", "1", "yes", "y"})
