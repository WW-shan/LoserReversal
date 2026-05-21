"""Fetch Hyperliquid funding history."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from infra.hyperliquid_client import HyperliquidClient


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
    rows = client._post_info(
        {
            "type": "fundingHistory",
            "coin": symbol,
            "startTime": int(start_ts.timestamp() * 1000),
            "endTime": int(end_ts.timestamp() * 1000),
        }
    )

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
        return pd.DataFrame(columns=["funding_rate", "premium"], index=empty_index)

    return frame.set_index("timestamp").sort_index()
