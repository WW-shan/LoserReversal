from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts import backfill_candles


def test_backfill_fetches_only_hl_unlock_tokens(mocker, tmp_path: Path, capsys):
    read_unlocks = mocker.patch.object(
        backfill_candles,
        "read_unlocks",
        return_value=_unlocks_frame(),
    )
    fetch_candles = mocker.patch.object(backfill_candles, "fetch_candles", return_value=_candles())
    write_candles = mocker.patch.object(backfill_candles, "write_candles")
    mocker.patch.object(backfill_candles, "CANDLES_DIR", tmp_path)

    assert backfill_candles.main(["--start", "2023-01-01", "--end", "2023-01-03"]) == 0

    read_unlocks.assert_called_once()
    assert [call.args[0] for call in fetch_candles.call_args_list] == ["BTC", "ETH"]
    assert [call.args[1] for call in fetch_candles.call_args_list] == ["1d", "1d"]
    assert [call.args[1] for call in write_candles.call_args_list] == ["BTC", "ETH"]
    assert "total tokens: 2" in capsys.readouterr().out


def test_backfill_missing_only_skips_existing_file_covering_start(
    mocker,
    tmp_path: Path,
    capsys,
):
    candles_dir = tmp_path / "candles"
    candles_dir.mkdir()
    _existing_candles("2023-01-01").to_parquet(candles_dir / "BTC_1d.parquet", index=False)
    mocker.patch.object(backfill_candles, "CANDLES_DIR", candles_dir)
    mocker.patch.object(backfill_candles, "read_unlocks", return_value=_unlocks_frame())
    fetch_candles = mocker.patch.object(backfill_candles, "fetch_candles", return_value=_candles())
    write_candles = mocker.patch.object(backfill_candles, "write_candles")

    assert (
        backfill_candles.main(
            ["--start", "2023-01-01", "--end", "2023-01-03", "--missing-only"]
        )
        == 0
    )

    assert [call.args[0] for call in fetch_candles.call_args_list] == ["ETH"]
    assert [call.args[1] for call in write_candles.call_args_list] == ["ETH"]
    assert "tokens skipped: 1" in capsys.readouterr().out


def test_backfill_logs_warning_and_continues_after_token_exception(
    mocker,
    tmp_path: Path,
    caplog,
    capsys,
):
    mocker.patch.object(backfill_candles, "CANDLES_DIR", tmp_path)
    mocker.patch.object(backfill_candles, "read_unlocks", return_value=_unlocks_frame())
    write_candles = mocker.patch.object(backfill_candles, "write_candles")

    def fetch(symbol: str, interval: str, start: str, end: str):
        if symbol == "BTC":
            raise RuntimeError("snapshot unavailable")
        return _candles()

    mocker.patch.object(backfill_candles, "fetch_candles", side_effect=fetch)

    assert backfill_candles.main(["--start", "2023-01-01", "--end", "2023-01-03"]) == 0

    assert [call.args[1] for call in write_candles.call_args_list] == ["ETH"]
    assert "failed to backfill BTC" in caplog.text
    assert "tokens failed: 1" in capsys.readouterr().out


def test_backfill_tokens_option_bypasses_unlocks_and_prints_summary(
    mocker,
    tmp_path: Path,
    capsys,
):
    read_unlocks = mocker.patch.object(backfill_candles, "read_unlocks")
    fetch_candles = mocker.patch.object(backfill_candles, "fetch_candles", return_value=_candles())
    mocker.patch.object(backfill_candles, "write_candles")
    mocker.patch.object(backfill_candles, "CANDLES_DIR", tmp_path)

    assert (
        backfill_candles.main(
            ["--start", "2023-01-01", "--end", "2023-01-03", "--tokens", "BTC, SOL"]
        )
        == 0
    )

    read_unlocks.assert_not_called()
    assert [call.args[0] for call in fetch_candles.call_args_list] == ["BTC", "SOL"]
    out = capsys.readouterr().out
    assert "total tokens: 2" in out
    assert "tokens fetched OK: 2" in out
    assert "range covered: 2023-01-01T00:00:00+00:00 -> 2023-01-02T00:00:00+00:00" in out


def _unlocks_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "token": ["BTC", "ETH", "OP"],
            "coingecko_id": ["bitcoin", "ethereum", "optimism"],
            "unlock_date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]),
            "unlock_pct": [0.02, 0.03, 0.04],
            "category": ["insiders", "community", "airdrop"],
            "has_hl_perp": [True, True, False],
            "vesting_type": ["cliff", "linear", "step"],
        }
    )


def _candles() -> pd.DataFrame:
    index = pd.date_range("2023-01-01", periods=2, freq="1D", tz="UTC", name="timestamp")
    return pd.DataFrame(
        {
            "open": [1.0, 2.0],
            "high": [1.5, 2.5],
            "low": [0.5, 1.5],
            "close": [1.2, 2.2],
            "volume": [100.0, 200.0],
        },
        index=index,
    )


def _existing_candles(start: str) -> pd.DataFrame:
    return _candles().loc[start:].reset_index()
