"""Tests for DuckDB-backed Parquet storage."""

from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from infra.storage import (
    read_fills,
    query,
    read_candles,
    read_funding,
    read_unlocks,
    read_wallets,
    write_candles,
    write_fills_parquet,
    write_funding,
    write_unlocks_csv_to_parquet,
    write_wallets_parquet,
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
        "vesting_type",
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


def _wallet_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "eth_address": ["0xabc", "0xdef"],
            "account_value": [100.0, 0.0],
            "pnl_alltime": [-12_000.0, -50_000.0],
            "vlm_alltime": [1_500_000.0, 20_000_000.0],
            "roi_alltime": [-0.5, -0.9],
            "display_name": ["alpha", None],
            "pnl_month": [-1000.0, -2000.0],
            "vlm_month": [100_000.0, 200_000.0],
            "added_at": pd.to_datetime(
                ["2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"],
                utc=True,
            ),
        }
    )


def test_write_and_read_wallets_roundtrip_preserves_schema(tmp_path: Path):
    frame = _wallet_frame()
    path = tmp_path / "anti_alpha_wallets.parquet"

    written = write_wallets_parquet(frame, path=path)
    actual = read_wallets(path=path)
    schema = pq.read_schema(written)

    assert written == path
    assert schema.field("added_at").type == pa.timestamp("us", tz="UTC")
    pd.testing.assert_frame_equal(
        actual.sort_values("eth_address").reset_index(drop=True),
        frame.sort_values("eth_address").reset_index(drop=True),
        check_freq=False,
    )


def test_read_wallets_filters_by_min_pnl_loss(tmp_path: Path):
    path = write_wallets_parquet(_wallet_frame(), path=tmp_path / "wallets.parquet")

    actual = read_wallets(path=path, min_pnl_loss=-20_000.0)

    assert actual["eth_address"].tolist() == ["0xdef"]


def test_write_and_read_fills_roundtrip_preserves_time_index(tmp_path: Path):
    index = pd.date_range("2026-01-01", periods=2, freq="1h", tz="UTC", name="time")
    frame = pd.DataFrame(
        {
            "coin": ["BTC", "ETH"],
            "side": ["B", "A"],
            "dir": ["Open Long", "Close Short"],
            "px": [43000.0, 3000.0],
            "sz": [0.1, 1.5],
            "start_position": [0.0, -1.5],
            "closed_pnl": [-10.0, 15.0],
            "fee": [0.1, 0.2],
            "oid": [1001, 1002],
            "tid": [2001, 2002],
            "hash": ["0x1", "0x2"],
            "crossed": [False, True],
            "liquidation": [False, True],
        },
        index=index,
    )
    path = tmp_path / "fills.parquet"

    written = write_fills_parquet(frame, "0xABC", path=path)
    actual = read_fills("0xABC", path=path)
    schema = pq.read_schema(written)

    assert written == path
    assert schema.field("time").type == pa.timestamp("us", tz="UTC")
    pd.testing.assert_frame_equal(actual, frame, check_freq=False)


def test_read_fills_filters_by_start_and_end(tmp_path: Path):
    index = pd.date_range("2026-01-01", periods=5, freq="1h", tz="UTC", name="time")
    frame = pd.DataFrame(
        {
            "coin": ["BTC"] * 5,
            "side": ["B"] * 5,
            "dir": ["Open Long"] * 5,
            "px": [43000.0] * 5,
            "sz": [0.1] * 5,
            "start_position": [0.0] * 5,
            "closed_pnl": [0.0] * 5,
            "fee": [0.1] * 5,
            "oid": range(1001, 1006),
            "tid": range(2001, 2006),
            "hash": [f"0x{i}" for i in range(5)],
            "crossed": [False] * 5,
            "liquidation": [False] * 5,
        },
        index=index,
    )
    path = write_fills_parquet(frame, "0xabc", path=tmp_path / "fills.parquet")

    actual = read_fills(
        "0xabc",
        start="2026-01-01T01:00:00Z",
        end="2026-01-01T03:00:00Z",
        path=path,
    )

    pd.testing.assert_frame_equal(actual, frame.iloc[1:4], check_freq=False)
