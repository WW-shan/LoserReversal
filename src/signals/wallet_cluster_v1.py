from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pandas as pd

from signals.wallet_reverse_v1 import (
    MAX_RETAIL_NOTIONAL,
    MIN_RETAIL_NOTIONAL,
    OPEN_DIR_TO_REVERSE_SIDE,
)


EVENT_COLUMNS = [
    "entry_time",
    "exit_time",
    "side",
    "cluster_size",
    "confidence_score",
]


def cluster_signal(
    pool_fills: dict[str, pd.DataFrame],
    coin_universe: set[str] | None = None,
    min_wallets: int = 3,
    window_minutes: int = 30,
    holding_hours: float = 4.0,
    coin_filter: Iterable[str] | None = None,
) -> dict[str, pd.DataFrame]:
    if min_wallets < 1:
        raise ValueError("min_wallets must be at least 1")
    if window_minutes <= 0:
        raise ValueError("window_minutes must be greater than 0")
    if holding_hours <= 0:
        raise ValueError("holding_hours must be greater than 0")

    fills = _cluster_input_frame(pool_fills, coin_universe, coin_filter)
    if fills.empty:
        return {}

    events_by_coin: dict[str, pd.DataFrame] = {}
    for coin, coin_fills in fills.groupby("coin", sort=False):
        coin_events = _coin_cluster_events(
            coin_fills.sort_values(["entry_time", "wallet", "source_order"]),
            min_wallets=min_wallets,
            window_minutes=window_minutes,
            holding_hours=holding_hours,
        )
        if not coin_events.empty:
            events_by_coin[str(coin)] = coin_events
    return events_by_coin


def _cluster_input_frame(
    pool_fills: dict[str, pd.DataFrame],
    coin_universe: set[str] | None,
    coin_filter: Iterable[str] | None,
) -> pd.DataFrame:
    frames = [
        _wallet_events(address, fills, source_position)
        for source_position, (address, fills) in enumerate(pool_fills.items())
    ]
    if not frames:
        return _empty_input_frame()

    combined = pd.concat(frames, ignore_index=True)
    if combined.empty:
        return _empty_input_frame()

    if coin_universe is not None:
        combined = combined.loc[combined["coin"].isin({str(coin) for coin in coin_universe})].copy()
    if coin_filter is not None:
        combined = combined.loc[combined["coin"].isin({str(coin) for coin in coin_filter})].copy()
    if combined.empty:
        return _empty_input_frame()
    return combined.sort_values(["coin", "entry_time", "source_order"]).reset_index(drop=True)


def _wallet_events(address: str, fills: pd.DataFrame, source_position: int) -> pd.DataFrame:
    if fills.empty or not {"coin", "dir", "px", "sz"}.issubset(fills.columns):
        return _empty_input_frame()

    frame = fills.copy()
    if "time" in frame.columns:
        frame["entry_time"] = pd.to_datetime(frame["time"], utc=True, errors="coerce")
    else:
        frame["entry_time"] = pd.to_datetime(frame.index, utc=True, errors="coerce")

    frame["wallet"] = str(address).lower()
    frame["coin"] = frame["coin"].astype("string")
    frame["dir"] = frame["dir"].astype("string")
    frame["side"] = frame["dir"].map(OPEN_DIR_TO_REVERSE_SIDE)
    frame["px"] = pd.to_numeric(frame["px"], errors="coerce")
    frame["sz"] = pd.to_numeric(frame["sz"], errors="coerce")
    frame["notional"] = frame["px"] * frame["sz"]
    frame["source_order"] = range(
        source_position * max(len(frame), 1),
        source_position * max(len(frame), 1) + len(frame),
    )

    mask = frame["entry_time"].notna()
    mask &= frame["coin"].notna()
    mask &= frame["side"].notna()
    mask &= frame["notional"].between(MIN_RETAIL_NOTIONAL, MAX_RETAIL_NOTIONAL, inclusive="both")
    return frame.loc[
        mask,
        ["wallet", "coin", "entry_time", "dir", "side", "notional", "source_order"],
    ].reset_index(drop=True)


def _coin_cluster_events(
    fills: pd.DataFrame,
    *,
    min_wallets: int,
    window_minutes: int,
    holding_hours: float,
) -> pd.DataFrame:
    candidates: list[dict[str, Any]] = []
    window = pd.Timedelta(minutes=window_minutes)

    for direction, direction_fills in fills.groupby("dir", sort=False):
        side = OPEN_DIR_TO_REVERSE_SIDE[str(direction)]
        direction_fills = direction_fills.sort_values(["entry_time", "wallet", "source_order"])
        timestamps = list(direction_fills["entry_time"])
        for current_time in timestamps:
            window_start = current_time - window
            in_window = direction_fills.loc[
                (direction_fills["entry_time"] >= window_start)
                & (direction_fills["entry_time"] <= current_time)
            ]
            wallet_count = int(in_window["wallet"].nunique())
            if wallet_count < min_wallets:
                continue
            candidates.append(
                {
                    "entry_time": pd.Timestamp(current_time),
                    "exit_time": pd.Timestamp(current_time)
                    + pd.to_timedelta(float(holding_hours), unit="h"),
                    "side": side,
                    "cluster_size": wallet_count,
                    "confidence_score": wallet_count / min_wallets,
                }
            )

    if not candidates:
        return _empty_events()

    frame = pd.DataFrame(candidates, columns=EVENT_COLUMNS).sort_values(
        ["entry_time", "side"],
    )
    frame = frame.drop_duplicates(subset=["entry_time", "side"], keep="first")
    cooldown = pd.to_timedelta(float(holding_hours), unit="h")
    kept: list[pd.DataFrame] = []
    cooldown_until: pd.Timestamp | None = None
    for entry_time, same_time in frame.groupby("entry_time", sort=True):
        timestamp = pd.Timestamp(entry_time)
        if cooldown_until is not None and timestamp < cooldown_until:
            continue
        kept.append(same_time)
        cooldown_until = timestamp + cooldown

    if not kept:
        return _empty_events()
    return pd.concat(kept, ignore_index=True)[EVENT_COLUMNS]


def _empty_input_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "wallet": pd.Series(dtype="string"),
            "coin": pd.Series(dtype="string"),
            "entry_time": pd.Series(dtype="datetime64[ns, UTC]"),
            "dir": pd.Series(dtype="string"),
            "side": pd.Series(dtype="string"),
            "notional": pd.Series(dtype="float64"),
            "source_order": pd.Series(dtype="int64"),
        }
    )


def _empty_events() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "entry_time": pd.Series(dtype="datetime64[ns, UTC]"),
            "exit_time": pd.Series(dtype="datetime64[ns, UTC]"),
            "side": pd.Series(dtype="string"),
            "cluster_size": pd.Series(dtype="int64"),
            "confidence_score": pd.Series(dtype="float64"),
        },
        columns=EVENT_COLUMNS,
    )
