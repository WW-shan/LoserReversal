"""DuckDB-backed Parquet storage helpers."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


PARQUET_DIR = Path(__file__).resolve().parents[2] / "data" / "parquet"
UNLOCK_COLUMNS = [
    "token",
    "coingecko_id",
    "unlock_date",
    "unlock_pct",
    "category",
    "has_hl_perp",
    "vesting_type",
]
UNLOCK_SCHEMA = pa.schema(
    [
        ("token", pa.string()),
        ("coingecko_id", pa.string()),
        ("unlock_date", pa.date32()),
        ("unlock_pct", pa.float64()),
        ("category", pa.string()),
        ("has_hl_perp", pa.bool_()),
        ("vesting_type", pa.string()),
    ]
)
WALLET_COLUMNS = [
    "eth_address",
    "account_value",
    "pnl_alltime",
    "vlm_alltime",
    "roi_alltime",
    "display_name",
    "pnl_month",
    "vlm_month",
    "added_at",
]
WALLET_SCHEMA = pa.schema(
    [
        ("eth_address", pa.string()),
        ("account_value", pa.float64()),
        ("pnl_alltime", pa.float64()),
        ("vlm_alltime", pa.float64()),
        ("roi_alltime", pa.float64()),
        ("display_name", pa.string()),
        ("pnl_month", pa.float64()),
        ("vlm_month", pa.float64()),
        ("added_at", pa.timestamp("us", tz="UTC")),
    ]
)
FILL_COLUMNS = [
    "time",
    "coin",
    "side",
    "dir",
    "px",
    "sz",
    "start_position",
    "closed_pnl",
    "fee",
    "oid",
    "tid",
    "hash",
    "crossed",
    "liquidation",
]
FILL_SCHEMA = pa.schema(
    [
        ("time", pa.timestamp("us", tz="UTC")),
        ("coin", pa.string()),
        ("side", pa.string()),
        ("dir", pa.string()),
        ("px", pa.float64()),
        ("sz", pa.float64()),
        ("start_position", pa.float64()),
        ("closed_pnl", pa.float64()),
        ("fee", pa.float64()),
        ("oid", pa.int64()),
        ("tid", pa.int64()),
        ("hash", pa.string()),
        ("crossed", pa.bool_()),
        ("liquidation", pa.bool_()),
    ]
)


def write_candles(
    df: pd.DataFrame,
    symbol: str,
    interval: str,
    path: Path | None = None,
) -> Path:
    target = path or PARQUET_DIR / "candles" / f"{symbol}_{interval}.parquet"
    _write_time_indexed_frame(df, target)
    return target


def read_candles(
    symbol: str,
    interval: str,
    start: datetime | str | None = None,
    end: datetime | str | None = None,
    path: Path | None = None,
) -> pd.DataFrame:
    source = path or PARQUET_DIR / "candles" / f"{symbol}_{interval}.parquet"
    return _read_time_indexed_frame(
        source,
        ["open", "high", "low", "close", "volume"],
        start=start,
        end=end,
    )


def write_funding(df: pd.DataFrame, symbol: str, path: Path | None = None) -> Path:
    target = path or PARQUET_DIR / "funding" / f"{symbol}.parquet"
    _write_time_indexed_frame(df, target)
    return target


def read_funding(
    symbol: str,
    start: datetime | str | None = None,
    end: datetime | str | None = None,
    path: Path | None = None,
) -> pd.DataFrame:
    source = path or PARQUET_DIR / "funding" / f"{symbol}.parquet"
    return _read_time_indexed_frame(
        source,
        ["funding_rate", "premium"],
        start=start,
        end=end,
    )


def write_unlocks_csv_to_parquet(csv_path: Path, parquet_path: Path | None = None) -> Path:
    target = parquet_path or PARQUET_DIR / "unlocks.parquet"
    target.parent.mkdir(parents=True, exist_ok=True)

    frame = pd.read_csv(csv_path, dtype={"vesting_type": "string"})
    if "vesting_type" not in frame.columns:
        frame["vesting_type"] = pd.Series(pd.NA, index=frame.index, dtype="string")
    frame = frame[UNLOCK_COLUMNS]
    frame["unlock_date"] = pd.to_datetime(frame["unlock_date"]).dt.date
    frame["unlock_pct"] = frame["unlock_pct"].astype("float64")
    frame["has_hl_perp"] = _coerce_bool_series(frame["has_hl_perp"])
    frame["vesting_type"] = frame["vesting_type"].astype("string")

    table = pa.Table.from_pandas(frame, schema=UNLOCK_SCHEMA, preserve_index=False)
    pq.write_table(table, target, compression=None, use_dictionary=False, row_group_size=64)
    return target


def read_unlocks(path: Path | None = None, category: str | None = None) -> pd.DataFrame:
    source = path or PARQUET_DIR / "unlocks.parquet"
    params: dict[str, Any] = {"path": str(source)}
    sql = f"SELECT {', '.join(UNLOCK_COLUMNS)} FROM read_parquet($path)"
    if category is not None:
        params["category"] = category
        sql = f"{sql} WHERE category = $category"
    sql = f"{sql} ORDER BY unlock_date, token, category, vesting_type"

    with duckdb.connect(database=":memory:") as conn:
        frame = conn.execute(sql, params).df()

    frame["vesting_type"] = frame["vesting_type"].astype(pd.StringDtype(storage="python"))
    return frame


def write_wallets_parquet(df: pd.DataFrame, path: Path | None = None) -> Path:
    target = path or PARQUET_DIR / "anti_alpha_wallets.parquet"
    target.parent.mkdir(parents=True, exist_ok=True)

    frame = df.copy()[WALLET_COLUMNS]
    frame["eth_address"] = frame["eth_address"].astype("string").str.lower()
    frame["added_at"] = pd.to_datetime(frame["added_at"], utc=True)
    for column in ["account_value", "pnl_alltime", "vlm_alltime", "roi_alltime", "pnl_month", "vlm_month"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("float64")

    table = pa.Table.from_pandas(frame, schema=WALLET_SCHEMA, preserve_index=False)
    pq.write_table(table, target, compression=None, use_dictionary=False, row_group_size=64)
    return target


def read_wallets(path: Path | None = None, min_pnl_loss: float | None = None) -> pd.DataFrame:
    source = path or PARQUET_DIR / "anti_alpha_wallets.parquet"
    params: dict[str, Any] = {"path": str(source)}
    sql = f"SELECT {', '.join(WALLET_COLUMNS)} FROM read_parquet($path)"
    if min_pnl_loss is not None:
        params["min_pnl_loss"] = min_pnl_loss
        sql = f"{sql} WHERE pnl_alltime <= $min_pnl_loss"

    with duckdb.connect(database=":memory:") as conn:
        frame = conn.execute(sql, params).df()

    frame["added_at"] = pd.to_datetime(frame["added_at"], utc=True)
    return frame


def write_fills_parquet(df: pd.DataFrame, address: str, path: Path | None = None) -> Path:
    target = path or PARQUET_DIR / "fills" / f"{address.lower()}.parquet"
    target.parent.mkdir(parents=True, exist_ok=True)

    frame = df.copy()
    if "time" not in frame.columns:
        frame.index = pd.DatetimeIndex(pd.to_datetime(frame.index, utc=True), name="time")
        frame = frame.reset_index()
    frame = frame[FILL_COLUMNS]
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    for column in ["px", "sz", "start_position", "closed_pnl", "fee"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("float64")
    for column in ["oid", "tid"]:
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype("int64")
    frame["crossed"] = frame["crossed"].fillna(False).astype("bool")
    frame["liquidation"] = frame["liquidation"].fillna(False).astype("bool")

    table = pa.Table.from_pandas(frame, schema=FILL_SCHEMA, preserve_index=False)
    pq.write_table(table, target, compression=None, use_dictionary=False, row_group_size=256)
    return target


def read_fills(
    address: str,
    start: datetime | str | None = None,
    end: datetime | str | None = None,
    path: Path | None = None,
) -> pd.DataFrame:
    source = path or PARQUET_DIR / "fills" / f"{address.lower()}.parquet"
    params: dict[str, Any] = {"path": str(source)}
    filters = []
    if start is not None:
        params["start"] = _coerce_utc_timestamp(start).to_pydatetime()
        filters.append("time >= $start")
    if end is not None:
        params["end"] = _coerce_utc_timestamp(end).to_pydatetime()
        filters.append("time <= $end")

    sql = f"SELECT {', '.join(FILL_COLUMNS)} FROM read_parquet($path)"
    if filters:
        sql = f"{sql} WHERE {' AND '.join(filters)}"
    sql = f"{sql} ORDER BY time"

    with duckdb.connect(database=":memory:") as conn:
        frame = conn.execute(sql, params).df()

    frame.index = pd.DatetimeIndex(pd.to_datetime(frame.pop("time"), utc=True), name="time")
    return frame


def query(sql: str, **params: Any) -> pd.DataFrame:
    with duckdb.connect(database=":memory:") as conn:
        if params:
            return conn.execute(sql, params).df()
        return conn.execute(sql).df()


def _write_time_indexed_frame(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = df.copy()
    frame.index = _coerce_utc_index(frame.index)
    frame.index.name = "timestamp"
    frame.reset_index().to_parquet(path, index=False)


def _read_time_indexed_frame(
    path: Path,
    columns: list[str],
    start: datetime | str | None = None,
    end: datetime | str | None = None,
) -> pd.DataFrame:
    params: dict[str, Any] = {"path": str(path)}
    filters = []
    if start is not None:
        params["start"] = _coerce_utc_timestamp(start).to_pydatetime()
        filters.append("timestamp >= $start")
    if end is not None:
        params["end"] = _coerce_utc_timestamp(end).to_pydatetime()
        filters.append("timestamp <= $end")

    selected = ", ".join(["timestamp", *columns])
    sql = f"SELECT {selected} FROM read_parquet($path)"
    if filters:
        sql = f"{sql} WHERE {' AND '.join(filters)}"
    sql = f"{sql} ORDER BY timestamp"

    with duckdb.connect(database=":memory:") as conn:
        frame = conn.execute(sql, params).df()

    frame.index = pd.DatetimeIndex(pd.to_datetime(frame.pop("timestamp"), utc=True), name="timestamp")
    return frame


def _coerce_utc_index(index: pd.Index) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.to_datetime(index, utc=True), name="timestamp")


def _coerce_utc_timestamp(value: datetime | str) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tz is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _coerce_bool_series(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.astype("bool")
    return series.astype("string").str.lower().map({"true": True, "false": False}).astype("bool")
