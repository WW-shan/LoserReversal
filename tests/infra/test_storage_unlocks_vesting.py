from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from infra.storage import read_unlocks, write_unlocks_csv_to_parquet


def test_unlocks_parquet_roundtrip_preserves_vesting_type(tmp_path: Path):
    csv_path = tmp_path / "unlocks.csv"
    parquet_path = tmp_path / "unlocks.parquet"
    csv_path.write_text(
        "\n".join(
            [
                "token,coingecko_id,unlock_date,unlock_pct,category,has_hl_perp,vesting_type",
                "ARB,arbitrum,2026-01-01,0.020000,insiders,true,cliff",
                "OP,optimism,2026-01-02,0.010000,community,false,linear",
            ]
        ),
        encoding="utf-8",
    )

    written = write_unlocks_csv_to_parquet(csv_path, parquet_path)
    actual = read_unlocks(written)
    schema = pq.read_schema(written)

    assert actual["vesting_type"].tolist() == ["cliff", "linear"]
    assert actual["vesting_type"].dtype == pd.StringDtype(storage="python")
    assert schema.field("vesting_type").type == pa.string()


def test_read_unlocks_handles_old_schema_without_vesting_type(tmp_path: Path):
    parquet_path = tmp_path / "old_unlocks.parquet"
    frame = pd.DataFrame(
        {
            "token": ["ARB"],
            "coingecko_id": ["arbitrum"],
            "unlock_date": pd.to_datetime(["2026-01-01"]).date,
            "unlock_pct": [0.02],
            "category": ["insiders"],
            "has_hl_perp": [True],
        }
    )
    table = pa.Table.from_pandas(frame, preserve_index=False)
    pq.write_table(table, parquet_path)

    actual = read_unlocks(parquet_path)

    assert "vesting_type" in actual.columns
    assert actual["vesting_type"].isna().all()
    assert actual["vesting_type"].dtype == pd.StringDtype(storage="python")


def test_write_unlocks_rejects_invalid_vesting_type(tmp_path: Path):
    csv_path = tmp_path / "unlocks.csv"
    csv_path.write_text(
        "\n".join(
            [
                "token,coingecko_id,unlock_date,unlock_pct,category,has_hl_perp,vesting_type",
                "ARB,arbitrum,2026-01-01,0.020000,insiders,true,cliffe",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="cliffe"):
        write_unlocks_csv_to_parquet(csv_path, tmp_path / "unlocks.parquet")


def test_write_unlocks_normalizes_vesting_type_case(tmp_path: Path):
    csv_path = tmp_path / "unlocks.csv"
    parquet_path = tmp_path / "unlocks.parquet"
    csv_path.write_text(
        "\n".join(
            [
                "token,coingecko_id,unlock_date,unlock_pct,category,has_hl_perp,vesting_type",
                "ARB,arbitrum,2026-01-01,0.020000,insiders,true,Cliff",
            ]
        ),
        encoding="utf-8",
    )

    written = write_unlocks_csv_to_parquet(csv_path, parquet_path)
    actual = read_unlocks(written)

    assert actual["vesting_type"].tolist() == ["cliff"]
