"""Tests for DuckDB-backed Parquet storage."""

from pathlib import Path

import pandas as pd

from infra.storage import read_candles, write_candles


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
    pd.testing.assert_frame_equal(actual, frame.loc["2026-01-03":"2026-01-07"], check_freq=False)
