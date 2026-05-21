"""DuckDB-backed Parquet storage helpers."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd


PARQUET_DIR = Path(__file__).resolve().parents[2] / "data" / "parquet"


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
