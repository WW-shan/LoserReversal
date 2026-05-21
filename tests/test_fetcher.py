"""Tests for fetcher.load_events and price fetching."""

import json
from pathlib import Path

import pandas as pd
import pytest

from unlock_validation.fetcher import load_events


def test_load_events_returns_dataframe(fixtures_dir: Path):
    df = load_events(fixtures_dir / "tokenunlocks_sample.csv")
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 5


def test_load_events_parses_required_columns(fixtures_dir: Path):
    df = load_events(fixtures_dir / "tokenunlocks_sample.csv")
    required = {"token", "coingecko_id", "unlock_date", "unlock_pct", "category", "has_hl_perp"}
    assert required.issubset(df.columns)


def test_load_events_parses_unlock_date_as_datetime(fixtures_dir: Path):
    df = load_events(fixtures_dir / "tokenunlocks_sample.csv")
    assert pd.api.types.is_datetime64_any_dtype(df["unlock_date"])


def test_load_events_normalizes_category_to_lowercase(fixtures_dir: Path):
    df = load_events(fixtures_dir / "tokenunlocks_sample.csv")
    assert df["category"].str.islower().all()


def test_load_events_parses_has_hl_perp_as_bool(fixtures_dir: Path):
    df = load_events(fixtures_dir / "tokenunlocks_sample.csv")
    assert df["has_hl_perp"].dtype == bool


def test_load_events_filters_below_pct_threshold(fixtures_dir: Path):
    df = load_events(fixtures_dir / "tokenunlocks_sample.csv", min_pct=0.02)
    # APT has 0.018 → excluded
    assert "APT" not in df["token"].values
    assert len(df) == 4
