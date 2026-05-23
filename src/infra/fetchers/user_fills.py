"""Fetch paginated Hyperliquid user fills."""

from __future__ import annotations

import warnings
from datetime import datetime
from typing import Any

import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential

from infra.hyperliquid_client import HyperliquidClient


FILL_CAP = 2000
MAX_PAGES = 50
FILL_FRAME_COLUMNS = [
    "coin",
    "side",
    "dir",
    "px",
    "sz",
    "start_position",
    "closed_pnl",
    "fee",
    "oid",
    "tid",
    "hash",
    "crossed",
    "liquidation",
]
FLOAT_COLUMNS = ["px", "sz", "start_position", "closed_pnl", "fee"]
INTEGER_COLUMNS = ["oid", "tid"]


def fetch_user_fills(
    address: str,
    start: datetime | int,
    end: datetime | int,
    client: HyperliquidClient | None = None,
) -> pd.DataFrame:
    client = client or HyperliquidClient()
    normalized_address = address.lower()
    cursor = _coerce_ms(start)
    end_ms = _coerce_ms(end)
    rows = []
    previous_boundary_tids: set[Any] = set()

    for _ in range(MAX_PAGES):
        chunk = _post_user_fills(
            client,
            {
                "type": "userFillsByTime",
                "user": normalized_address,
                "startTime": cursor,
                "endTime": end_ms,
            },
        )
        if not chunk:
            break

        rows.extend(chunk)
        if len(chunk) < FILL_CAP:
            break

        first_time = int(chunk[0]["time"])
        last_time = int(chunk[-1]["time"])
        last_tids = {row.get("tid") for row in chunk if int(row["time"]) == last_time}
        if first_time == last_time:
            warnings.warn(
                "userFillsByTime returned a cap-sized page in a single millisecond; "
                "later fills at that timestamp may be unavailable",
                RuntimeWarning,
                stacklevel=2,
            )
            next_cursor = last_time + 1
        else:
            next_cursor = last_time
        if next_cursor > end_ms:
            break
        if next_cursor < cursor:
            break
        if next_cursor == cursor and last_tids == previous_boundary_tids:
            break
        previous_boundary_tids = last_tids
        cursor = next_cursor
    else:
        warnings.warn("userFillsByTime pagination hard cap hit", RuntimeWarning, stacklevel=2)

    return _fills_to_frame(rows)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _post_user_fills(client: HyperliquidClient, payload: dict[str, Any]) -> list[dict[str, Any]]:
    return client._post_info(payload)


def _fills_to_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame((_normalize_fill(row) for row in rows), columns=["time", *FILL_FRAME_COLUMNS])
    if frame.empty:
        return _empty_frame()

    frame["time"] = pd.to_datetime(frame["time"], unit="ms", utc=True)
    for column in FLOAT_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("float64")
    for column in INTEGER_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype("int64")
    frame["crossed"] = frame["crossed"].fillna(False).astype("bool")
    frame["liquidation"] = frame["liquidation"].astype("bool")

    return frame.drop_duplicates(subset="tid", keep="last").set_index("time").sort_index()


def _normalize_fill(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "time": row.get("time"),
        "coin": row.get("coin"),
        "side": row.get("side"),
        "dir": row.get("dir"),
        "px": row.get("px"),
        "sz": row.get("sz"),
        "start_position": row.get("startPosition"),
        "closed_pnl": row.get("closedPnl"),
        "fee": row.get("fee"),
        "oid": row.get("oid"),
        "tid": row.get("tid"),
        "hash": row.get("hash"),
        "crossed": row.get("crossed"),
        "liquidation": row.get("liquidation") is not None,
    }


def _coerce_ms(value: datetime | int) -> int:
    if isinstance(value, int):
        if value < 10_000_000_000:
            raise ValueError("integer timestamps must be unix milliseconds")
        return value
    ts = pd.Timestamp(value)
    if ts.tz is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return int(ts.timestamp() * 1000)


def _empty_frame() -> pd.DataFrame:
    columns = {
        "coin": pd.Series(dtype="object"),
        "side": pd.Series(dtype="object"),
        "dir": pd.Series(dtype="object"),
        "hash": pd.Series(dtype="object"),
        "crossed": pd.Series(dtype="bool"),
        "liquidation": pd.Series(dtype="bool"),
    }
    columns.update({column: pd.Series(dtype="float64") for column in FLOAT_COLUMNS})
    columns.update({column: pd.Series(dtype="int64") for column in INTEGER_COLUMNS})
    return pd.DataFrame(
        columns,
        columns=FILL_FRAME_COLUMNS,
        index=pd.DatetimeIndex([], name="time", tz="UTC"),
    )
