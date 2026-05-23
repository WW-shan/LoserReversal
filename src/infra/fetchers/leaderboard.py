"""Fetch Hyperliquid leaderboard rows."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd
import requests
from tenacity import retry, stop_after_attempt, wait_exponential


LEADERBOARD_URL = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
LEADERBOARD_HEADERS = {
    "accept": "*/*",
    "origin": "https://app.hyperliquid.xyz",
    "user-agent": "Mozilla/5.0",
}
LEADERBOARD_COLUMNS = [
    "eth_address",
    "account_value",
    "display_name",
    "pnl_day",
    "pnl_week",
    "pnl_month",
    "pnl_alltime",
    "vlm_day",
    "vlm_week",
    "vlm_month",
    "vlm_alltime",
    "roi_day",
    "roi_week",
    "roi_month",
    "roi_alltime",
]
NUMERIC_COLUMNS = [column for column in LEADERBOARD_COLUMNS if column not in {"eth_address", "display_name"}]
WINDOW_SUFFIXES = {
    "day": "day",
    "week": "week",
    "month": "month",
    "allTime": "alltime",
}


def fetch_leaderboard(client: Any | None = None) -> pd.DataFrame:
    data = _load_leaderboard(client)
    rows = data.get("leaderboardRows", [])
    frame = pd.DataFrame((_normalize_row(row) for row in rows), columns=LEADERBOARD_COLUMNS)
    if frame.empty:
        return _empty_frame()

    for column in NUMERIC_COLUMNS:
        frame[column] = _coerce_float_series(frame[column])

    return frame.sort_values("pnl_alltime", ascending=True, na_position="last").reset_index(drop=True)


def _load_leaderboard(client: Any | None) -> dict[str, Any]:
    if client is None:
        return _http_get_leaderboard()
    if hasattr(client, "get_leaderboard"):
        return client.get_leaderboard()
    response = client.get(LEADERBOARD_URL, headers=LEADERBOARD_HEADERS, timeout=20)
    response.raise_for_status()
    return response.json()


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _http_get_leaderboard() -> dict[str, Any]:
    response = requests.get(LEADERBOARD_URL, headers=LEADERBOARD_HEADERS, timeout=20)
    response.raise_for_status()
    return response.json()


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    record = {
        "eth_address": str(row.get("ethAddress", "")).lower(),
        "account_value": row.get("accountValue"),
        "display_name": row.get("displayName"),
    }
    for metric in ("pnl", "vlm", "roi"):
        for suffix in WINDOW_SUFFIXES.values():
            record[f"{metric}_{suffix}"] = None

    for window_name, performance in row.get("windowPerformances", []):
        suffix = WINDOW_SUFFIXES.get(window_name)
        if suffix is None:
            continue
        for metric in ("pnl", "vlm", "roi"):
            record[f"{metric}_{suffix}"] = performance.get(metric)

    return record


def _coerce_float_series(series: pd.Series) -> pd.Series:
    coerced = pd.to_numeric(series, errors="coerce").astype("float64")
    return coerced.where(coerced.map(math.isfinite)).astype("float64")


def _empty_frame() -> pd.DataFrame:
    columns = {
        "eth_address": pd.Series(dtype="object"),
        "display_name": pd.Series(dtype="object"),
    }
    columns.update({column: pd.Series(dtype="float64") for column in NUMERIC_COLUMNS})
    return pd.DataFrame(columns, columns=LEADERBOARD_COLUMNS)
