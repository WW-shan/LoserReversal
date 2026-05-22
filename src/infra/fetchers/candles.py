"""Fetch Hyperliquid candle snapshots."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from infra.hyperliquid_client import HyperliquidClient


CANDLE_CAP = 5000
MAX_PAGES = 100


def _coerce_utc_timestamp(value: datetime | str) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tz is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def fetch_candles(
    symbol: str,
    interval: str,
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
                "type": "candleSnapshot",
                "req": {
                    "coin": symbol,
                    "interval": interval,
                    "startTime": cursor,
                    "endTime": end_ms,
                },
            }
        )
        if not chunk:
            break

        rows.extend(chunk)
        if len(chunk) < CANDLE_CAP:
            break

        last_time = int(chunk[-1]["T"])
        if last_time >= end_ms:
            break

        next_cursor = last_time + 1
        if next_cursor <= cursor:
            break
        cursor = next_cursor

    frame = pd.DataFrame(
        [
            {
                "timestamp": pd.to_datetime(row["t"], unit="ms", utc=True),
                "open": float(row["o"]),
                "high": float(row["h"]),
                "low": float(row["l"]),
                "close": float(row["c"]),
                "volume": float(row["v"]),
            }
            for row in rows
        ],
        columns=["timestamp", "open", "high", "low", "close", "volume"],
    )

    if frame.empty:
        empty_index = pd.DatetimeIndex([], name="timestamp", tz="UTC")
        return pd.DataFrame(
            {
                "open": pd.Series(dtype="float64"),
                "high": pd.Series(dtype="float64"),
                "low": pd.Series(dtype="float64"),
                "close": pd.Series(dtype="float64"),
                "volume": pd.Series(dtype="float64"),
            },
            index=empty_index,
        )

    return frame.drop_duplicates(subset="timestamp", keep="last").set_index("timestamp").sort_index()
