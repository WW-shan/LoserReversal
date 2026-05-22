"""Fetch Hyperliquid funding history."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from infra.hyperliquid_client import HyperliquidClient


FUNDING_CAP = 500
MAX_PAGES = 100


def _coerce_utc_timestamp(value: datetime | str) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tz is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def fetch_funding(
    symbol: str,
    start: datetime | str,
    end: datetime | str,
    client: HyperliquidClient | None = None,
) -> pd.DataFrame:
    client = client or HyperliquidClient()
    start_ts = _coerce_utc_timestamp(start)
    end_ts = _coerce_utc_timestamp(end)
    end_ms = int(end_ts.timestamp() * 1000)
    cursor = int(start_ts.timestamp() * 1000)
    rows = []

    for _ in range(MAX_PAGES):
        chunk = client._post_info(
            {
                "type": "fundingHistory",
                "coin": symbol,
                "startTime": cursor,
                "endTime": end_ms,
            }
        )
        if not chunk:
            break

        rows.extend(chunk)
        if len(chunk) < FUNDING_CAP:
            break

        last_time = int(chunk[-1]["time"])
        if last_time >= end_ms:
            break

        next_cursor = last_time + 1
        if next_cursor <= cursor:
            break
        cursor = next_cursor

    frame = pd.DataFrame(
        [
            {
                "timestamp": pd.to_datetime(row["time"], unit="ms", utc=True),
                "funding_rate": float(row["fundingRate"]),
                "premium": float(row["premium"]),
            }
            for row in rows
        ],
        columns=["timestamp", "funding_rate", "premium"],
    )

    if frame.empty:
        empty_index = pd.DatetimeIndex([], name="timestamp", tz="UTC")
        return pd.DataFrame(
            {
                "funding_rate": pd.Series(dtype="float64"),
                "premium": pd.Series(dtype="float64"),
            },
            index=empty_index,
        )

    return frame.drop_duplicates(subset="timestamp", keep="last").set_index("timestamp").sort_index()
