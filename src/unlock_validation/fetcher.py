"""Fetcher for unlock events (CSV) and price history (CoinGecko)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


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
