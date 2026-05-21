"""Fetch Hyperliquid candle snapshots."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from infra.hyperliquid_client import HyperliquidClient


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
    rows = client._post_info(
        {
            "type": "candleSnapshot",
            "req": {
                "coin": symbol,
                "interval": interval,
                "startTime": int(start_ts.timestamp() * 1000),
                "endTime": int(end_ts.timestamp() * 1000),
            },
        }
    )

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

    return frame.set_index("timestamp").sort_index()
