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


def _leaderboard_frame(rows: list[tuple[str, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "eth_address": wallet,
                "account_value": account_value,
                "display_name": wallet,
                "pnl_day": 0.0,
                "pnl_week": 0.0,
                "pnl_month": 0.0,
                "pnl_alltime": 0.0,
                "vlm_day": 0.0,
                "vlm_week": 0.0,
                "vlm_month": 0.0,
                "vlm_alltime": 0.0,
                "roi_day": 0.0,
                "roi_week": 0.0,
                "roi_month": 0.0,
                "roi_alltime": 0.0,
            }
            for wallet, account_value in rows
        ]
    )


def test_build_bot_pool_writes_bot_wallets_and_excludes_humans(mocker, tmp_path: Path) -> None:
    import scripts.build_bot_pool as builder

    leaderboard = _leaderboard_frame(
        [
            ("0xbot", 25_000.0),
            ("0xhuman", 25_000.0),
        ]
    )
    mocker.patch.object(builder, "fetch_leaderboard", return_value=leaderboard)

    def _fake_fetch(address: str, start, end):
        if address.lower() == "0xbot":
            return _bot_fills()
        return _human_fills()

    mocker.patch.object(builder, "fetch_user_fills", side_effect=_fake_fetch)

    out_path = tmp_path / "bot_wallets.parquet"
    result = builder.build_bot_pool(
        out=out_path,
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
        throttle_ms=0,
    )

    written = pd.read_parquet(out_path)
    assert written.columns.tolist() == [
        "wallet",
        "bot_score",
        "hour_entropy",
        "size_cv",
        "coin_diversity",
        "session_gap_min",
        "round_number_pct",
    ]
    assert written["wallet"].tolist() == ["0xbot"]
    assert written["bot_score"].iloc[0] >= 0.8
    assert result["written_count"] == 1
    assert result["human_excluded_count"] == 1


def test_build_bot_pool_honours_top_n_and_max_wallets(mocker, tmp_path: Path) -> None:
    import scripts.build_bot_pool as builder

    leaderboard = _leaderboard_frame(
        [
            ("0xa", 25_000.0),
            ("0xb", 25_000.0),
            ("0xc", 25_000.0),
        ]
    )
    mocker.patch.object(builder, "fetch_leaderboard", return_value=leaderboard)
    fetched_addresses: list[str] = []

    def _fake_fetch(address: str, start, end):
        fetched_addresses.append(address)
        return _bot_fills()

    mocker.patch.object(builder, "fetch_user_fills", side_effect=_fake_fetch)

    result = builder.build_bot_pool(
        out=tmp_path / "bot_wallets.parquet",
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
        top_n=3,
        max_wallets=2,
        throttle_ms=0,
    )

    written = pd.read_parquet(tmp_path / "bot_wallets.parquet")
    assert fetched_addresses == ["0xa", "0xb", "0xc"]
    assert written["wallet"].tolist() == ["0xa", "0xb"]
    assert result["leaderboard_count"] == 3
    assert result["written_count"] == 2


def test_build_bot_pool_logs_warning_when_fill_fetch_fails(mocker, tmp_path: Path, capsys) -> None:
    import scripts.build_bot_pool as builder

    leaderboard = _leaderboard_frame(
        [
            ("0xboom", 25_000.0),
            ("0xbot", 25_000.0),
        ]
    )
    mocker.patch.object(builder, "fetch_leaderboard", return_value=leaderboard)

    def _fake_fetch(address: str, start, end):
        if address == "0xboom":
            raise RuntimeError("network failure")
        return _bot_fills()

    mocker.patch.object(builder, "fetch_user_fills", side_effect=_fake_fetch)

    result = builder.build_bot_pool(
        out=tmp_path / "bot_wallets.parquet",
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
        throttle_ms=0,
    )

    stderr = capsys.readouterr().err
    assert "warning" in stderr.lower()
    assert result["wallets_failed"] == 1
    assert result["written_count"] == 1


def test_build_bot_pool_main_entrypoint_prints_summary(mocker, tmp_path: Path, capsys) -> None:
    import scripts.build_bot_pool as builder

    leaderboard = _leaderboard_frame([("0xbot", 25_000.0)])
    mocker.patch.object(builder, "fetch_leaderboard", return_value=leaderboard)
    mocker.patch.object(builder, "fetch_user_fills", return_value=_bot_fills())

    out_path = tmp_path / "bot_wallets.parquet"
    mocker.patch(
        "sys.argv",
        [
            "build_bot_pool.py",
            "--out",
            str(out_path),
            "--throttle-ms",
            "0",
            "--as-of",
            "2026-05-26T00:00:00Z",
        ],
    )

    exit_code = builder.main()

    assert exit_code == 0
    stdout = capsys.readouterr().out
    assert "bot pool" in stdout.lower()
    assert "written" in stdout.lower()
    assert out_path.exists()


def test_build_bot_pool_rejects_invalid_max_wallets(mocker, capsys) -> None:
    import scripts.build_bot_pool as builder

    mocker.patch("sys.argv", ["build_bot_pool.py", "--max-wallets", "0"])

    with pytest.raises(SystemExit):
        builder._parse_args()

    assert "--max-wallets must be greater than 0" in capsys.readouterr().err
