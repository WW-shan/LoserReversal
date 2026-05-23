from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts import backfill_funding


def test_backfill_writes_per_symbol_parquet(mocker, tmp_path: Path, capsys):
    mocker.patch.object(backfill_funding, "FUNDING_DIR", tmp_path)
    mocker.patch.object(backfill_funding, "_top_volume_tokens", return_value=["BTC", "ETH"])
    fetch_funding = mocker.patch.object(backfill_funding, "fetch_funding", return_value=_funding())
    write_funding = mocker.patch.object(backfill_funding, "write_funding")

    assert (
        backfill_funding.main(
            ["--start", "2023-05-01", "--end", "2023-05-02", "--top-n", "2"]
        )
        == 0
    )

    assert [call.args[0] for call in fetch_funding.call_args_list] == ["BTC", "ETH"]
    assert [call.args[1] for call in write_funding.call_args_list] == ["BTC", "ETH"]
    assert [call.kwargs["path"] for call in write_funding.call_args_list] == [
        tmp_path / "BTC.parquet",
        tmp_path / "ETH.parquet",
    ]
    assert "total tokens: 2" in capsys.readouterr().out


def test_backfill_skips_existing_when_missing_only(mocker, tmp_path: Path, capsys):
    tmp_path.mkdir(exist_ok=True)
    _existing_funding("2023-05-01").to_parquet(tmp_path / "BTC.parquet", index=False)
    mocker.patch.object(backfill_funding, "FUNDING_DIR", tmp_path)
    mocker.patch.object(backfill_funding, "_top_volume_tokens", return_value=["BTC", "ETH"])
    fetch_funding = mocker.patch.object(backfill_funding, "fetch_funding", return_value=_funding())
    write_funding = mocker.patch.object(backfill_funding, "write_funding")

    assert (
        backfill_funding.main(
            ["--start", "2023-05-01", "--end", "2023-05-02", "--missing-only"]
        )
        == 0
    )

    assert [call.args[0] for call in fetch_funding.call_args_list] == ["ETH"]
    assert [call.args[1] for call in write_funding.call_args_list] == ["ETH"]
    assert "tokens skipped: 1" in capsys.readouterr().out


def test_backfill_handles_per_symbol_failure_without_aborting(
    mocker,
    tmp_path: Path,
    caplog,
    capsys,
):
    mocker.patch.object(backfill_funding, "FUNDING_DIR", tmp_path)
    mocker.patch.object(backfill_funding, "_top_volume_tokens", return_value=["BTC", "ETH"])
    write_funding = mocker.patch.object(backfill_funding, "write_funding")

    def fetch(symbol: str, start: object, end: object):
        if symbol == "BTC":
            raise RuntimeError("funding unavailable")
        return _funding()

    mocker.patch.object(backfill_funding, "fetch_funding", side_effect=fetch)

    assert backfill_funding.main(["--start", "2023-05-01", "--end", "2023-05-02"]) == 0

    assert [call.args[1] for call in write_funding.call_args_list] == ["ETH"]
    assert "failed to backfill BTC" in caplog.text
    assert "tokens failed: 1" in capsys.readouterr().out


def test_backfill_top_n_filters_by_volume(mocker, tmp_path: Path):
    mocker.patch.object(backfill_funding, "FUNDING_DIR", tmp_path)
    client = mocker.Mock()
    client.universe_with_volumes.return_value = {
        "DOGE": 10.0,
        "BTC": 100.0,
        "ETH": 50.0,
        "SOL": 75.0,
    }
    mocker.patch.object(backfill_funding, "HyperliquidClient", return_value=client)
    fetch_funding = mocker.patch.object(backfill_funding, "fetch_funding", return_value=_funding())
    mocker.patch.object(backfill_funding, "write_funding")

    assert (
        backfill_funding.main(
            ["--start", "2023-05-01", "--end", "2023-05-02", "--top-n", "2"]
        )
        == 0
    )

    assert [call.args[0] for call in fetch_funding.call_args_list] == ["BTC", "SOL"]


def _funding() -> pd.DataFrame:
    index = pd.date_range("2023-05-01", periods=2, freq="1h", tz="UTC", name="timestamp")
    return pd.DataFrame(
        {
            "funding_rate": [0.0001, 0.0002],
            "premium": [0.0003, 0.0004],
        },
        index=index,
    )


def _existing_funding(start: str) -> pd.DataFrame:
    return _funding().loc[start:].reset_index()
