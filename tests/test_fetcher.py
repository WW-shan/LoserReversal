"""Tests for fetcher.load_events and price fetching."""

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from unlock_validation.fetcher import fetch_prices, load_events


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


def test_fetch_prices_returns_dataframe_with_date_index(tmp_path, fixtures_dir, mocker):
    """Loads from CoinGecko, returns DataFrame indexed by date."""
    mock_get = mocker.patch("unlock_validation.fetcher.requests.get")
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "prices": [
            [1726358400000, 0.60],
            [1726444800000, 0.595],
        ]
    }
    mock_get.return_value.raise_for_status = lambda: None

    start = datetime(2025, 9, 15, tzinfo=timezone.utc)
    end = datetime(2025, 9, 16, tzinfo=timezone.utc)
    df = fetch_prices("arbitrum", start, end, cache_dir=tmp_path)

    assert isinstance(df, pd.DataFrame)
    assert "price" in df.columns
    assert pd.api.types.is_datetime64_any_dtype(df.index)
    assert len(df) == 2


def test_fetch_prices_caches_to_disk(tmp_path, mocker):
    """Second call with same arguments must not hit the network."""
    mock_get = mocker.patch("unlock_validation.fetcher.requests.get")
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"prices": [[1726358400000, 0.60]]}
    mock_get.return_value.raise_for_status = lambda: None

    start = datetime(2025, 9, 15, tzinfo=timezone.utc)
    end = datetime(2025, 9, 16, tzinfo=timezone.utc)

    fetch_prices("arbitrum", start, end, cache_dir=tmp_path)
    fetch_prices("arbitrum", start, end, cache_dir=tmp_path)

    assert mock_get.call_count == 1


def test_fetch_prices_uses_cached_file_after_restart(tmp_path, mocker, fixtures_dir):
    """Writes cache file and subsequent call (even with fresh mock state) reads it."""
    import shutil

    cache_file = tmp_path / "arbitrum_1726358400_1726444800.json"
    shutil.copy(fixtures_dir / "coingecko_arb.json", cache_file)

    mock_get = mocker.patch("unlock_validation.fetcher.requests.get")

    start = datetime.fromtimestamp(1726358400, tz=timezone.utc)
    end = datetime.fromtimestamp(1726444800, tz=timezone.utc)
    df = fetch_prices("arbitrum", start, end, cache_dir=tmp_path)

    assert mock_get.call_count == 0
    assert len(df) == 5
