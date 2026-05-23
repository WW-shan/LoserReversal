from __future__ import annotations

import pandas as pd


REQUIRED_EVENT_COLUMNS = {
    "token",
    "unlock_date",
    "unlock_pct",
    "category",
    "has_hl_perp",
    "vesting_type",
}


def filter_events(
    events: pd.DataFrame,
    *,
    min_unlock_pct: float,
    require_hl_perp: bool,
    coverage: pd.DataFrame | None,
) -> pd.DataFrame:
    """Apply common filters: pct threshold, has_hl_perp, coverage_status == 'ok'."""
    if events.empty or not REQUIRED_EVENT_COLUMNS.issubset(events.columns):
        return pd.DataFrame(columns=events.columns)

    frame = events.copy()
    frame["token"] = frame["token"].astype("string")
    frame["unlock_date"] = pd.to_datetime(frame["unlock_date"], utc=True, errors="coerce")
    frame["unlock_pct"] = pd.to_numeric(frame["unlock_pct"], errors="coerce")
    frame = frame.dropna(subset=["token", "unlock_date"])

    mask = frame["unlock_pct"] >= float(min_unlock_pct)
    if require_hl_perp:
        mask &= coerce_bool_series(frame["has_hl_perp"])
    frame = frame.loc[mask].copy()
    if frame.empty:
        return frame

    if coverage is not None:
        frame = _filter_covered_events(frame, coverage)
    if frame.empty:
        return frame

    return frame.reset_index(drop=True)


def emit_pair_signals(
    *,
    events: pd.DataFrame,
    prices: dict[str, pd.Series],
    entry_offset_days: int | None = None,
    exit_offset_days: int | None = None,
    pre_window: pd.Timedelta | None = None,
    post_window: pd.Timedelta | None = None,
) -> dict[str, tuple[pd.Series, pd.Series]]:
    """Generic entry/exit signal emitter using offsets relative to unlock_date."""
    if events.empty or not prices or not {"token", "unlock_date"}.issubset(events.columns):
        return {}

    entry_offset, exit_offset = _resolve_offsets(
        entry_offset_days=entry_offset_days,
        exit_offset_days=exit_offset_days,
        pre_window=pre_window,
        post_window=post_window,
    )
    frame = events.copy()
    frame["token"] = frame["token"].astype("string")
    frame["unlock_date"] = pd.to_datetime(frame["unlock_date"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["token", "unlock_date"])
    if frame.empty:
        return {}

    frame = frame.sort_values(["token", "unlock_date"])
    result: dict[str, tuple[pd.Series, pd.Series]] = {}
    for token, token_events in frame.groupby("token", sort=False):
        token_name = str(token)
        if token_name not in prices:
            continue

        close_index = _coerce_price_index(prices[token_name].index)
        if close_index.empty:
            continue

        entries = pd.Series(False, index=close_index, dtype=bool)
        exits = pd.Series(False, index=close_index, dtype=bool)
        last_exit: pd.Timestamp | None = None

        for unlock_ts in token_events["unlock_date"]:
            entry_ts = unlock_ts + entry_offset
            exit_ts = unlock_ts + exit_offset
            if entry_ts not in close_index or exit_ts not in close_index:
                continue
            if last_exit is not None and entry_ts <= last_exit:
                continue

            entries.loc[entry_ts] = True
            exits.loc[exit_ts] = True
            last_exit = exit_ts

        if entries.any():
            result[token_name] = (entries, exits)

    return result


def coerce_bool_series(series: pd.Series) -> pd.Series:
    return series.astype("string").str.lower().isin({"true", "1", "1.0", "yes", "y", "t"})


def _filter_covered_events(events: pd.DataFrame, coverage: pd.DataFrame) -> pd.DataFrame:
    required_columns = {"token", "unlock_date", "coverage_status"}
    if coverage.empty or not required_columns.issubset(coverage.columns):
        return events.iloc[0:0].copy()

    coverage_frame = coverage.copy()
    coverage_frame["token"] = coverage_frame["token"].astype("string")
    coverage_frame["unlock_date"] = _coverage_key(coverage_frame["unlock_date"])
    coverage_frame = coverage_frame.dropna(subset=["token", "unlock_date"])
    coverage_frame = coverage_frame.loc[
        coverage_frame["coverage_status"].astype("string").eq("ok"),
        ["token", "unlock_date"],
    ].drop_duplicates()
    if coverage_frame.empty:
        return events.iloc[0:0].copy()

    frame = events.copy()
    frame["_coverage_unlock_date"] = frame["unlock_date"].dt.normalize()
    frame = frame.merge(
        coverage_frame,
        left_on=["token", "_coverage_unlock_date"],
        right_on=["token", "unlock_date"],
        how="inner",
        suffixes=("", "_coverage"),
    )
    return frame.drop(columns=["_coverage_unlock_date", "unlock_date_coverage"], errors="ignore")


def _coverage_key(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values, utc=True, errors="coerce").dt.normalize()


def _coerce_price_index(index: pd.Index) -> pd.DatetimeIndex:
    price_index = pd.DatetimeIndex(index)
    if price_index.tz is None:
        return pd.DatetimeIndex(price_index, tz="UTC")
    return price_index.tz_convert("UTC")


def _resolve_offsets(
    *,
    entry_offset_days: int | None,
    exit_offset_days: int | None,
    pre_window: pd.Timedelta | None,
    post_window: pd.Timedelta | None,
) -> tuple[pd.Timedelta, pd.Timedelta]:
    if entry_offset_days is not None and exit_offset_days is not None:
        return pd.Timedelta(days=entry_offset_days), pd.Timedelta(days=exit_offset_days)
    if pre_window is not None and post_window is not None:
        return -pd.Timedelta(pre_window), pd.Timedelta(post_window)
    raise ValueError("entry and exit offsets must both be provided")
