from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from infra.data_audit import compute_event_candle_coverage
from infra.storage import UNLOCK_SCHEMA, write_candles


def test_coverage_status_ok_when_60_pre_days_present(tmp_path: Path):
    unlocks_path = _write_unlocks(tmp_path, "OK", "2026-03-01")
    candles_dir = tmp_path / "candles"
    _write_candles(candles_dir, "OK", "2025-12-31")

    actual = compute_event_candle_coverage(unlocks_path, candles_dir)

    assert actual.loc[0, "coverage_status"] == "ok"
    assert actual.loc[0, "pre_event_days"] == 60


def test_coverage_status_listing_after_when_first_candle_post_unlock(tmp_path: Path):
    unlocks_path = _write_unlocks(tmp_path, "POST", "2026-03-01")
    candles_dir = tmp_path / "candles"
    _write_candles(candles_dir, "POST", "2026-03-02")

    actual = compute_event_candle_coverage(unlocks_path, candles_dir)

    assert actual.loc[0, "coverage_status"] == "listing_after"
    assert pd.isna(actual.loc[0, "pre_event_days"])


def test_coverage_status_insufficient_pre_days_when_less_than_60(tmp_path: Path):
    unlocks_path = _write_unlocks(tmp_path, "SHORT", "2026-03-01")
    candles_dir = tmp_path / "candles"
    _write_candles(candles_dir, "SHORT", "2026-02-15")

    actual = compute_event_candle_coverage(unlocks_path, candles_dir)

    assert actual.loc[0, "coverage_status"] == "insufficient_pre_days"
    assert actual.loc[0, "pre_event_days"] == 14


def test_coverage_status_no_candle_file_when_parquet_missing(tmp_path: Path):
    unlocks_path = _write_unlocks(tmp_path, "MISS", "2026-03-01")

    actual = compute_event_candle_coverage(unlocks_path, tmp_path / "candles")

    assert actual.loc[0, "coverage_status"] == "no_candle_file"
    assert pd.isna(actual.loc[0, "candle_earliest"])
    assert pd.isna(actual.loc[0, "pre_event_days"])


def _write_unlocks(tmp_path: Path, token: str, unlock_date: str) -> Path:
    path = tmp_path / "unlocks.parquet"
    frame = pd.DataFrame(
        {
            "token": [token],
            "coingecko_id": [token.lower()],
            "unlock_date": pd.to_datetime([unlock_date]).date,
            "unlock_pct": [0.02],
            "category": ["insiders"],
            "has_hl_perp": [True],
            "vesting_type": ["cliff"],
        }
    )
    table = pa.Table.from_pandas(frame, schema=UNLOCK_SCHEMA, preserve_index=False)
    pq.write_table(table, path)
    return path


def _write_candles(candles_dir: Path, token: str, start: str) -> None:
    index = pd.DatetimeIndex(pd.to_datetime([start], utc=True), name="timestamp")
    frame = pd.DataFrame(
        {
            "open": [1.0],
            "high": [1.0],
            "low": [1.0],
            "close": [1.0],
            "volume": [1.0],
        },
        index=index,
    )
    write_candles(frame, token, "1d", candles_dir / f"{token}_1d.parquet")
