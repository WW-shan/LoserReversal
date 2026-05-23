from __future__ import annotations

from typing import Iterable

import pandas as pd


MIN_RETAIL_NOTIONAL = 1_000.0
MAX_RETAIL_NOTIONAL = 200_000.0
OPEN_DIR_TO_REVERSE_SIDE = {
    "Open Long": "short",
    "Open Short": "long",
}
EVENT_COLUMNS = [
    "coin",
    "entry_time",
    "exit_time",
    "side",
    "notional",
    "px",
    "sz",
    "dir",
]


def reverse_signal(
    fills_df: pd.DataFrame,
    holding_hours: float,
    coin_filter: Iterable[str] | None = None,
    side_filter: str | None = None,
) -> dict[str, tuple[pd.Series, pd.Series, str]]:
    events = reverse_signal_events(fills_df, holding_hours, coin_filter, side_filter)
    if events.empty:
        return {}

    result: dict[str, tuple[pd.Series, pd.Series, str]] = {}
    for coin, coin_events in events.groupby("coin", sort=False):
        index = pd.DatetimeIndex(
            sorted(set(coin_events["entry_time"]).union(set(coin_events["exit_time"]))),
            name="time",
        )
        entries = pd.Series(False, index=index, dtype=bool)
        exits = pd.Series(False, index=index, dtype=bool)
        entries.loc[coin_events["entry_time"].to_list()] = True
        exits.loc[coin_events["exit_time"].to_list()] = True

        sides = coin_events["side"].dropna().unique().tolist()
        side = str(sides[0]) if len(sides) == 1 else "mixed"
        result[str(coin)] = (entries, exits, side)

    return result


def reverse_signal_events(
    fills_df: pd.DataFrame,
    holding_hours: float,
    coin_filter: Iterable[str] | None = None,
    side_filter: str | None = None,
) -> pd.DataFrame:
    if holding_hours <= 0:
        raise ValueError("holding_hours must be greater than 0")
    if side_filter is not None and side_filter not in {"long", "short"}:
        raise ValueError("side_filter must be 'long' or 'short'")
    if fills_df.empty:
        return _empty_events()

    required = {"coin", "dir", "px", "sz"}
    if not required.issubset(fills_df.columns):
        return _empty_events()

    frame = fills_df.copy()
    if "time" in frame.columns:
        frame["entry_time"] = pd.to_datetime(frame["time"], utc=True, errors="coerce")
    else:
        frame["entry_time"] = pd.to_datetime(frame.index, utc=True, errors="coerce")

    frame["coin"] = frame["coin"].astype("string")
    frame["dir"] = frame["dir"].astype("string")
    frame["px"] = pd.to_numeric(frame["px"], errors="coerce")
    frame["sz"] = pd.to_numeric(frame["sz"], errors="coerce")
    frame["side"] = frame["dir"].map(OPEN_DIR_TO_REVERSE_SIDE)
    frame["notional"] = frame["px"] * frame["sz"]

    mask = frame["side"].notna()
    mask &= frame["entry_time"].notna()
    mask &= frame["coin"].notna()
    mask &= frame["notional"].between(MIN_RETAIL_NOTIONAL, MAX_RETAIL_NOTIONAL, inclusive="both")
    if coin_filter is not None:
        allowed = {str(coin) for coin in coin_filter}
        mask &= frame["coin"].isin(allowed)
    if side_filter is not None:
        mask &= frame["side"].eq(side_filter)

    events = frame.loc[mask, ["coin", "entry_time", "side", "notional", "px", "sz", "dir"]].copy()
    if events.empty:
        return _empty_events()

    events["exit_time"] = events["entry_time"] + pd.to_timedelta(float(holding_hours), unit="h")
    return events[EVENT_COLUMNS].sort_values(["coin", "entry_time", "side"]).reset_index(drop=True)


def _empty_events() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "coin": pd.Series(dtype="string"),
            "entry_time": pd.Series(dtype="datetime64[ns, UTC]"),
            "exit_time": pd.Series(dtype="datetime64[ns, UTC]"),
            "side": pd.Series(dtype="string"),
            "notional": pd.Series(dtype="float64"),
            "px": pd.Series(dtype="float64"),
            "sz": pd.Series(dtype="float64"),
            "dir": pd.Series(dtype="string"),
        },
        columns=EVENT_COLUMNS,
    )
