from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest


def _fill_row(
    time: pd.Timestamp,
    *,
    coin: str,
    sz: float,
) -> dict[str, object]:
    return {
        "time": time,
        "coin": coin,
        "side": "B",
        "dir": "Open Long",
        "px": 100.0,
        "sz": sz,
        "start_position": 0.0,
        "closed_pnl": 0.0,
        "fee": 0.0,
        "oid": 1,
        "tid": 1,
        "hash": "0x1",
        "crossed": False,
        "liquidation": False,
    }


def _fills_df(rows: list[dict[str, object]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    return frame.set_index("time").sort_index()


def _bot_fills() -> pd.DataFrame:
    base = pd.Timestamp("2026-05-01T00:00:00Z")
    return _fills_df(
        [
            _fill_row(base + pd.Timedelta(hours=i), coin="BTC", sz=1_000.0)
            for i in range(24)
        ]
    )


def _human_fills() -> pd.DataFrame:
    base = pd.Timestamp("2026-05-01T00:00:00Z")
    coins = ["BTC", "ETH", "SOL", "HYPE", "DOGE", "XRP", "BNB", "SUI"]
    gaps = [0, 7, 31, 215, 377, 600, 980, 1_440]
    sizes = [127.43, 981.27, 53.81, 2_345.67, 410.19, 88.42, 1_579.31, 231.76]
    return _fills_df(
        [
            _fill_row(base + pd.Timedelta(minutes=gaps[i]), coin=coins[i], sz=sizes[i])
            for i in range(len(coins))
        ]
    )


def _academic_pool(wallets: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "wallet": wallets,
            "account_value": [25_000.0] * len(wallets),
            "realized_loss_rate_90d": [0.60] * len(wallets),
            "leverage_avg_90d": [8.0] * len(wallets),
            "n_trades_90d": [80] * len(wallets),
            "size_cv_90d": [0.45] * len(wallets),
            "eligible_at": [pd.Timestamp("2026-05-26T00:00:00Z")] * len(wallets),
        }
    )


def test_build_clean_wallet_pool_writes_clean_and_excluded_outputs(
    mocker,
    tmp_path: Path,
) -> None:
    import scripts.build_clean_wallet_pool as builder

    academic_path = tmp_path / "academic_wallet_pool.parquet"
    clean_path = tmp_path / "clean_retail_pool.parquet"
    excluded_path = tmp_path / "excluded_bot_pool.parquet"
    funding_path = tmp_path / "wallet_funding_sources.parquet"

    _academic_pool(["0xbot", "0xhuman", "0xs1", "0xs2", "0xs3"]).to_parquet(
        academic_path,
        index=False,
    )
    pd.DataFrame(
        {
            "wallet": ["0xbot", "0xhuman", "0xs1", "0xs2", "0xs3"],
            "from_address": ["src-bot", "src-human", "src-sybil", "src-sybil", "src-sybil"],
        }
    ).to_parquet(funding_path, index=False)

    def _fake_fetch(address: str, start, end):
        if address == "0xbot":
            return _bot_fills()
        return _human_fills()

    mocker.patch.object(builder, "fetch_user_fills", side_effect=_fake_fetch)

    result = builder.build_clean_wallet_pool(
        academic_pool_path=academic_path,
        clean_out=clean_path,
        excluded_out=excluded_path,
        funding_sources_path=funding_path,
        throttle_ms=0,
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
    )

    clean = pd.read_parquet(clean_path)
    excluded = pd.read_parquet(excluded_path)

    assert clean["wallet"].tolist() == ["0xhuman"]
    assert set(excluded["wallet"]) == {"0xbot", "0xs1", "0xs2", "0xs3"}
    assert dict(zip(excluded["wallet"], excluded["reason"], strict=False)) == {
        "0xbot": "bot_score",
        "0xs1": "funding_source_cluster",
        "0xs2": "funding_source_cluster",
        "0xs3": "funding_source_cluster",
    }
    assert result["funnel"]["academic_pool"] == 5
    assert result["funnel"]["bot_score_excluded"] == 1
    assert result["funnel"]["funding_source_excluded"] == 3
    assert result["funnel"]["clean_retail_pool"] == 1


def test_build_clean_wallet_pool_handles_empty_academic_pool(mocker, tmp_path: Path) -> None:
    import scripts.build_clean_wallet_pool as builder

    academic_path = tmp_path / "academic_wallet_pool.parquet"
    _academic_pool([]).to_parquet(academic_path, index=False)
    fetch_user_fills = mocker.patch.object(builder, "fetch_user_fills")

    result = builder.build_clean_wallet_pool(
        academic_pool_path=academic_path,
        clean_out=tmp_path / "clean.parquet",
        excluded_out=tmp_path / "excluded.parquet",
        funding_sources_path=tmp_path / "missing_funding_sources.parquet",
        throttle_ms=0,
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
    )

    fetch_user_fills.assert_not_called()
    assert result["funnel"]["academic_pool"] == 0
    assert pd.read_parquet(tmp_path / "clean.parquet").empty
    assert pd.read_parquet(tmp_path / "excluded.parquet").empty


def test_build_clean_wallet_pool_excludes_wallets_when_fetch_retries_fail(
    mocker,
    tmp_path: Path,
) -> None:
    import scripts.build_clean_wallet_pool as builder

    academic_path = tmp_path / "academic_wallet_pool.parquet"
    clean_path = tmp_path / "clean.parquet"
    excluded_path = tmp_path / "excluded.parquet"
    _academic_pool(["0xboom", "0xhuman"]).to_parquet(academic_path, index=False)

    def _fake_fetch(address: str, start, end):
        if address == "0xboom":
            raise RuntimeError("network failure")
        return _human_fills()

    mocker.patch.object(builder, "fetch_user_fills", side_effect=_fake_fetch)

    result = builder.build_clean_wallet_pool(
        academic_pool_path=academic_path,
        clean_out=clean_path,
        excluded_out=excluded_path,
        funding_sources_path=tmp_path / "missing_funding_sources.parquet",
        throttle_ms=0,
        retry_backoff_seconds=0.0,
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
    )

    clean = pd.read_parquet(clean_path)
    excluded = pd.read_parquet(excluded_path)

    assert clean["wallet"].tolist() == ["0xhuman"]
    assert excluded["wallet"].tolist() == ["0xboom"]
    assert excluded["reason"].tolist() == ["fetch_failed"]
    assert result["wallets_failed"] == 1
    assert result["funnel"]["fetch_failed_excluded"] == 1


def test_build_clean_wallet_pool_retries_transient_fetch_failure(
    mocker,
    tmp_path: Path,
) -> None:
    import scripts.build_clean_wallet_pool as builder

    academic_path = tmp_path / "academic_wallet_pool.parquet"
    _academic_pool(["0xbot"]).to_parquet(academic_path, index=False)
    fetch_user_fills = mocker.patch.object(
        builder,
        "fetch_user_fills",
        side_effect=[RuntimeError("rate limited"), _bot_fills()],
    )

    result = builder.build_clean_wallet_pool(
        academic_pool_path=academic_path,
        clean_out=tmp_path / "clean.parquet",
        excluded_out=tmp_path / "excluded.parquet",
        funding_sources_path=tmp_path / "missing_funding_sources.parquet",
        throttle_ms=0,
        retry_backoff_seconds=0.0,
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
    )

    excluded = pd.read_parquet(tmp_path / "excluded.parquet")

    assert fetch_user_fills.call_count == 2
    assert result["wallets_failed"] == 0
    assert excluded["wallet"].tolist() == ["0xbot"]
    assert excluded["reason"].tolist() == ["bot_score"]


def test_build_clean_wallet_pool_respects_min_trades(mocker, tmp_path: Path) -> None:
    import scripts.build_clean_wallet_pool as builder

    academic_path = tmp_path / "academic_wallet_pool.parquet"
    clean_path = tmp_path / "clean.parquet"
    excluded_path = tmp_path / "excluded.parquet"
    _academic_pool(["0xthinbot"]).to_parquet(academic_path, index=False)
    mocker.patch.object(builder, "fetch_user_fills", return_value=_bot_fills())

    result = builder.build_clean_wallet_pool(
        academic_pool_path=academic_path,
        clean_out=clean_path,
        excluded_out=excluded_path,
        funding_sources_path=tmp_path / "missing_funding_sources.parquet",
        throttle_ms=0,
        min_trades_for_scoring=50,
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
    )

    clean = pd.read_parquet(clean_path)
    excluded = pd.read_parquet(excluded_path)

    assert clean["wallet"].tolist() == ["0xthinbot"]
    assert excluded.empty
    assert result["funnel"]["bot_score_excluded"] == 0
    assert result["funnel"]["clean_retail_pool"] == 1


def test_build_clean_wallet_pool_main_entrypoint_prints_summary(
    mocker,
    tmp_path: Path,
    capsys,
) -> None:
    import scripts.build_clean_wallet_pool as builder

    academic_path = tmp_path / "academic_wallet_pool.parquet"
    clean_path = tmp_path / "clean_retail_pool.parquet"
    excluded_path = tmp_path / "excluded_bot_pool.parquet"
    _academic_pool(["0xhuman"]).to_parquet(academic_path, index=False)
    mocker.patch.object(builder, "fetch_user_fills", return_value=_human_fills())
    mocker.patch(
        "sys.argv",
        [
            "build_clean_wallet_pool.py",
            "--academic-pool",
            str(academic_path),
            "--clean-out",
            str(clean_path),
            "--excluded-out",
            str(excluded_path),
            "--funding-sources",
            str(tmp_path / "missing_funding_sources.parquet"),
            "--throttle-ms",
            "0",
            "--as-of",
            "2026-05-26T00:00:00Z",
        ],
    )

    exit_code = builder.main()

    assert exit_code == 0
    captured = capsys.readouterr()
    stdout = captured.out
    stderr = captured.err
    assert "clean wallet pool funnel" in stdout.lower()
    assert "funding sources file not found" in stderr.lower()
    assert clean_path.exists()
    assert excluded_path.exists()


def test_build_clean_wallet_pool_parse_args_accepts_min_trades(mocker) -> None:
    import scripts.build_clean_wallet_pool as builder

    mocker.patch("sys.argv", ["build_clean_wallet_pool.py", "--min-trades", "25"])

    args = builder._parse_args()

    assert args.min_trades == 25


def test_build_clean_wallet_pool_rejects_invalid_min_trades(mocker, capsys) -> None:
    import scripts.build_clean_wallet_pool as builder

    mocker.patch("sys.argv", ["build_clean_wallet_pool.py", "--min-trades", "0"])

    with pytest.raises(SystemExit):
        builder._parse_args()

    assert "--min-trades must be greater than 0" in capsys.readouterr().err
