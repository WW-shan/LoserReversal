"""Fetcher for unlock events (CSV) and price history (CoinGecko)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
from tenacity import retry, stop_after_attempt, wait_exponential


def load_events(csv_path: Path, min_pct: float = 0.0) -> pd.DataFrame:
    """Load unlock events from a curated CSV.

    Expected columns: token, coingecko_id, unlock_date, unlock_pct, category, has_hl_perp.
    """
    df = pd.read_csv(csv_path)
    df["unlock_date"] = pd.to_datetime(df["unlock_date"], utc=True)
    df["category"] = df["category"].str.lower().str.strip()
    df["has_hl_perp"] = df["has_hl_perp"].astype(bool)
    df["unlock_pct"] = df["unlock_pct"].astype(float)
    df = df[df["unlock_pct"] >= min_pct].reset_index(drop=True)
    return df


COINGECKO_BASE = "https://api.coingecko.com/api/v3"


def _cache_key(coingecko_id: str, start: datetime, end: datetime) -> str:
    return f"{coingecko_id}_{int(start.timestamp())}_{int(end.timestamp())}.json"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _http_get_prices(coingecko_id: str, start: datetime, end: datetime) -> dict:
    """Fetch daily prices covering [start, end] via the free /market_chart?days=N endpoint.

    The /market_chart/range endpoint requires a paid plan; the days-based variant is free
    and returns up to 365 days. We compute days from `start` (clamped to 365) and trim
    the response to the requested range in the caller.
    """
    now = datetime.now(tz=start.tzinfo) if start.tzinfo else datetime.utcnow()
    days = max(1, min(365, (now - start).days + 2))
    url = f"{COINGECKO_BASE}/coins/{coingecko_id}/market_chart"
    response = requests.get(
        url,
        params={"vs_currency": "usd", "days": days, "interval": "daily"},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def fetch_prices(
    coingecko_id: str,
    start: datetime,
    end: datetime,
    cache_dir: Path,
) -> pd.DataFrame:
    """Fetch daily prices for a CoinGecko coin id over [start, end].

    Caches the raw JSON response on disk. Returns a DataFrame indexed by UTC datetime
    with a single 'price' column.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / _cache_key(coingecko_id, start, end)

    if cache_path.exists():
        data = json.loads(cache_path.read_text())
    else:
        data = _http_get_prices(coingecko_id, start, end)
        cache_path.write_text(json.dumps(data))

    rows = [
        {"timestamp": pd.to_datetime(ts_ms, unit="ms", utc=True), "price": price}
        for ts_ms, price in data.get("prices", [])
    ]
    df = pd.DataFrame(rows).set_index("timestamp")
    return df
