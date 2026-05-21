"""Tests for DuckDB-backed Parquet storage."""

from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from infra.storage import (
    query,
    read_candles,
    read_funding,
    read_unlocks,
    write_candles,
    write_funding,
    write_unlocks_csv_to_parquet,
)


def test_write_and_read_candles_roundtrip(tmp_path: Path):
    index = pd.date_range("2026-01-01", periods=3, freq="1D", tz="UTC", name="timestamp")
    frame = pd.DataFrame(
        {
            "open": [100.0, 101.0, 102.0],
            "high": [110.0, 111.0, 112.0],
            "low": [90.0, 91.0, 92.0],
            "close": [105.0, 106.0, 107.0],
            "volume": [1000.0, 1100.0, 1200.0],
        },
        index=index,
    )
    path = tmp_path / "BTC_1d.parquet"

    written = write_candles(frame, "BTC", "1d", path=path)
    actual = read_candles("BTC", "1d", path=path)

    assert written == path
    pd.testing.assert_frame_equal(actual, frame, check_freq=False)


def test_read_candles_filters_by_start_and_end(tmp_path: Path):
    index = pd.date_range("2026-01-01", periods=10, freq="1D", tz="UTC", name="timestamp")
    frame = pd.DataFrame(
        {
            "open": range(10),
            "high": range(10),
            "low": range(10),
            "close": range(10),
            "volume": range(10),
        },
        index=index,
        dtype="float64",
    )
    path = tmp_path / "ETH_1d.parquet"
    write_candles(frame, "ETH", "1d", path=path)

    actual = read_candles(
        "ETH",
        "1d",
        start="2026-01-03T00:00:00Z",
        end="2026-01-07T00:00:00Z",
        path=path,
    )

    assert len(actual) == 5
    pd.testing.assert_frame_equal(
        actual,
        frame.loc["2026-01-03":"2026-01-07"],
        check_freq=False,
    )


def test_write_and_read_funding_roundtrip(tmp_path: Path):
    index = pd.date_range("2026-01-01", periods=3, freq="1h", tz="UTC", name="timestamp")
    frame = pd.DataFrame(
        {
            "funding_rate": [0.0001, 0.0002, -0.0001],
            "premium": [0.0003, 0.0004, -0.0002],
        },
        index=index,
    )
    path = tmp_path / "BTC.parquet"

    written = write_funding(frame, "BTC", path=path)
    actual = read_funding("BTC", path=path)

    assert written == path
    pd.testing.assert_frame_equal(actual, frame, check_freq=False)


def test_write_unlocks_csv_to_parquet_preserves_schema(tmp_path: Path):
    csv_path = Path("data/seed/unlocks_curated.csv")
    parquet_path = tmp_path / "unlocks.parquet"

    written = write_unlocks_csv_to_parquet(csv_path, parquet_path)
    actual = pd.read_parquet(written)
    schema = pq.read_schema(written)

    assert written == parquet_path
    assert len(actual) >= 100
    assert list(actual.columns) == [
        "token",
        "coingecko_id",
        "unlock_date",
        "unlock_pct",
        "category",
        "has_hl_perp",
    ]
    assert schema.field("unlock_date").type == pa.date32()


def test_read_unlocks_filters_category(tmp_path: Path):
    csv_path = Path("data/seed/unlocks_curated.csv")
    expected = pd.read_csv(csv_path)
    parquet_path = write_unlocks_csv_to_parquet(csv_path, tmp_path / "unlocks.parquet")

    actual = read_unlocks(parquet_path, category="airdrop")

    assert len(actual) == int((expected["category"] == "airdrop").sum())
    assert set(actual["category"]) == {"airdrop"}


def test_query_runs_parameterized_duckdb_sql():
    actual = query("SELECT $value::INTEGER AS value", value=7)

    assert actual.to_dict(orient="records") == [{"value": 7}]
