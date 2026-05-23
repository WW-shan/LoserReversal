from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

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


def test_backfill_rejects_path_traversal_token_in_cli_args(mocker, tmp_path: Path):
    outside = tmp_path.parent / "evil_1d.parquet"
    mocker.patch.object(backfill_candles, "CANDLES_DIR", tmp_path)
    fetch_candles = mocker.patch.object(backfill_candles, "fetch_candles", return_value=_candles())
    write_candles = mocker.patch.object(backfill_candles, "write_candles")

    with pytest.raises(ValueError, match="invalid token"):
        backfill_candles.main(
            ["--start", "2023-01-01", "--end", "2023-01-03", "--tokens", "../evil"]
        )

    fetch_candles.assert_not_called()
    write_candles.assert_not_called()
    assert not outside.exists()


def test_backfill_rejects_invalid_interval(mocker, tmp_path: Path):
    mocker.patch.object(backfill_candles, "CANDLES_DIR", tmp_path)
    fetch_candles = mocker.patch.object(backfill_candles, "fetch_candles", return_value=_candles())
    write_candles = mocker.patch.object(backfill_candles, "write_candles")

    with pytest.raises(ValueError, match="invalid interval"):
        backfill_candles.main(
            ["--start", "2023-01-01", "--end", "2023-01-03", "--tokens", "BTC", "--interval", "foo"]
        )

    fetch_candles.assert_not_called()
    write_candles.assert_not_called()


def test_backfill_logs_and_skips_invalid_token_from_unlocks(
    mocker,
    tmp_path: Path,
    caplog,
    capsys,
):
    unlocks = _unlocks_frame()
    unlocks.loc[len(unlocks)] = [
        "../evil",
        "evil",
        pd.Timestamp("2026-01-04"),
        0.05,
        "insiders",
        True,
        "cliff",
    ]
    mocker.patch.object(backfill_candles, "CANDLES_DIR", tmp_path)
    mocker.patch.object(backfill_candles, "read_unlocks", return_value=unlocks)
    fetch_candles = mocker.patch.object(backfill_candles, "fetch_candles", return_value=_candles())
    mocker.patch.object(backfill_candles, "write_candles")

    assert backfill_candles.main(["--start", "2023-01-01", "--end", "2023-01-03"]) == 0

    assert [call.args[0] for call in fetch_candles.call_args_list] == ["BTC", "ETH"]
    assert "skipping invalid token from unlocks: ../EVIL" in caplog.text
    assert "tokens skipped: 1" in capsys.readouterr().out


def test_backfill_target_path_outside_dir_is_rejected(mocker, tmp_path: Path):
    class AcceptAllPattern:
        def match(self, value: str):
            return True

    mocker.patch.object(backfill_candles, "CANDLES_DIR", tmp_path)
    mocker.patch.object(backfill_candles, "_VALID_TOKEN", AcceptAllPattern(), create=True)
    fetch_candles = mocker.patch.object(backfill_candles, "fetch_candles", return_value=_candles())
    write_candles = mocker.patch.object(backfill_candles, "write_candles")

    with pytest.raises(ValueError, match="outside candles dir"):
        backfill_candles.main(
            ["--start", "2023-01-01", "--end", "2023-01-03", "--tokens", "../evil"]
        )

    fetch_candles.assert_not_called()
    write_candles.assert_not_called()


def test_backfill_empty_response_counted_as_empty_not_ok(
    mocker,
    tmp_path: Path,
    caplog,
    capsys,
):
    mocker.patch.object(backfill_candles, "CANDLES_DIR", tmp_path)
    mocker.patch.object(backfill_candles, "fetch_candles", return_value=_empty_candles())
    write_candles = mocker.patch.object(backfill_candles, "write_candles")

    assert (
        backfill_candles.main(
            ["--start", "2023-01-01", "--end", "2023-01-03", "--tokens", "CYBER"]
        )
        == 0
    )

    write_candles.assert_not_called()
    assert "empty candle response for CYBER" in caplog.text
    out = capsys.readouterr().out
    assert "tokens fetched OK: 0" in out
    assert "tokens empty: 1" in out


def test_backfill_stale_response_counted_as_stale(
    mocker,
    tmp_path: Path,
    caplog,
    capsys,
):
    mocker.patch.object(backfill_candles, "CANDLES_DIR", tmp_path)
    mocker.patch.object(backfill_candles, "fetch_candles", return_value=_candles())
    write_candles = mocker.patch.object(backfill_candles, "write_candles")

    assert (
        backfill_candles.main(
            ["--start", "2023-01-01", "--end", "2023-03-05", "--tokens", "OMNI"]
        )
        == 0
    )

    write_candles.assert_called_once()
    assert "stale candle response for OMNI" in caplog.text
    out = capsys.readouterr().out
    assert "tokens fetched OK: 0" in out
    assert "tokens stale: 1" in out


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


def _empty_candles() -> pd.DataFrame:
    index = pd.DatetimeIndex([], tz="UTC", name="timestamp")
    return pd.DataFrame(
        {
            "open": pd.Series(dtype="float64"),
            "high": pd.Series(dtype="float64"),
            "low": pd.Series(dtype="float64"),
            "close": pd.Series(dtype="float64"),
            "volume": pd.Series(dtype="float64"),
        },
        index=index,
    )


def _existing_candles(start: str) -> pd.DataFrame:
    return _candles().loc[start:].reset_index()
