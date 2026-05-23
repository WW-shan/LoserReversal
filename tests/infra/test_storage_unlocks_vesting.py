from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

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
