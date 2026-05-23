from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import requests


def _wallets() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "eth_address": ["0xaaa", "0xbbb"],
            "account_value": [1.0, 2.0],
            "pnl_alltime": [-10.0, -20.0],
            "vlm_alltime": [2_000_000.0, 1_000_000.0],
            "roi_alltime": [-0.1, -0.2],
            "display_name": ["a", "b"],
            "pnl_month": [0.0, 0.0],
            "vlm_month": [0.0, 0.0],
            "added_at": pd.to_datetime(["2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"], utc=True),
        }
    )


def _fills() -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=1, freq="1h", tz="UTC", name="time")
    return pd.DataFrame(
        {
            "coin": ["BTC"],
            "side": ["B"],
            "dir": ["Open Long"],
            "px": [50_000.0],
            "sz": [0.1],
            "start_position": [0.0],
            "closed_pnl": [0.0],
            "fee": [1.0],
            "oid": [1],
            "tid": [1],
            "hash": ["0x1"],
            "crossed": [False],
            "liquidation": [False],
        },
        index=index,
    )


def test_skip_existing_wallet_does_not_fetch_when_cached_parquet_has_rows(mocker, tmp_path):
    import scripts.fetch_pool_fills as fetch_pool_fills

    out_dir = tmp_path / "fills"
    out_dir.mkdir()
    cached_path = out_dir / "0xaaa.parquet"
    _fills().to_parquet(cached_path)

    read_wallets = mocker.patch.object(fetch_pool_fills, "read_wallets", return_value=_wallets())
    fetch_user_fills = mocker.patch.object(fetch_pool_fills, "fetch_user_fills")
    write_fills_parquet = mocker.patch.object(fetch_pool_fills, "write_fills_parquet")

    result = fetch_pool_fills.fetch_pool_fills(
        top_n=1,
        lookback_days=30,
        throttle_ms=0,
        out_dir=out_dir,
        skip_existing=True,
        now=datetime(2026, 2, 1, tzinfo=timezone.utc),
    )

    assert result["wallets_skipped"] == 1
    assert result["wallets_fetched"] == 0
    read_wallets.assert_called_once()
    fetch_user_fills.assert_not_called()
    write_fills_parquet.assert_not_called()


def test_skip_existing_false_always_fetches(mocker, tmp_path):
    import scripts.fetch_pool_fills as fetch_pool_fills

    out_dir = tmp_path / "fills"
    out_dir.mkdir()
    _fills().to_parquet(out_dir / "0xaaa.parquet")

    mocker.patch.object(fetch_pool_fills, "read_wallets", return_value=_wallets())
    fetch_user_fills = mocker.patch.object(fetch_pool_fills, "fetch_user_fills", return_value=_fills())
    write_fills_parquet = mocker.patch.object(fetch_pool_fills, "write_fills_parquet")

    result = fetch_pool_fills.fetch_pool_fills(
        top_n=1,
        lookback_days=30,
        throttle_ms=0,
        out_dir=out_dir,
        skip_existing=False,
        now=datetime(2026, 2, 1, tzinfo=timezone.utc),
    )

    assert result["wallets_fetched"] == 1
    fetch_user_fills.assert_called_once()
    write_fills_parquet.assert_called_once()


def test_failed_fetch_logs_warning_and_continues(mocker, capsys, tmp_path):
    import scripts.fetch_pool_fills as fetch_pool_fills

    out_dir = tmp_path / "fills"
    out_dir.mkdir()
    mocker.patch.object(fetch_pool_fills, "read_wallets", return_value=_wallets())

    def _fetch(address, start, end):
        if address == "0xaaa":
            raise requests.HTTPError("boom")
        return _fills()

    fetch_user_fills = mocker.patch.object(fetch_pool_fills, "fetch_user_fills", side_effect=_fetch)
    write_fills_parquet = mocker.patch.object(fetch_pool_fills, "write_fills_parquet")

    result = fetch_pool_fills.fetch_pool_fills(
        top_n=2,
        lookback_days=30,
        throttle_ms=0,
        out_dir=out_dir,
        skip_existing=False,
        now=datetime(2026, 2, 1, tzinfo=timezone.utc),
    )

    stderr = capsys.readouterr().err
    assert "warning" in stderr.lower()
    assert result["wallets_failed"] == 1
    assert result["wallets_fetched"] == 1
    assert fetch_user_fills.call_count == 2
    assert write_fills_parquet.call_count == 1
