from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest


def _fill_row(
    time: str,
    *,
    px: float = 100.0,
    sz: float = 1.0,
    closed_pnl: float = 0.0,
    direction: str = "Open Long",
) -> dict[str, object]:
    return {
        "time": pd.Timestamp(time, tz="UTC"),
        "coin": "BTC",
        "side": "B",
        "dir": direction,
        "px": px,
        "sz": sz,
        "start_position": 0.0,
        "closed_pnl": closed_pnl,
        "fee": 0.0,
        "oid": 1,
        "tid": 1,
        "hash": "0x1",
        "crossed": False,
        "liquidation": False,
    }


def _retail_open_close_fills(account_value: float, n_open: int = 60) -> pd.DataFrame:
    base = pd.Timestamp("2026-04-01T00:00:00Z")
    rows: list[dict[str, object]] = []
    leverage_targets = [account_value * 5, account_value * 10, account_value * 15]
    for i in range(n_open):
        notional = leverage_targets[i % 3]
        rows.append(
            _fill_row(
                (base + pd.Timedelta(hours=i)).isoformat(),
                px=100.0,
                sz=notional / 100.0,
                direction="Open Long" if i % 2 == 0 else "Open Short",
            )
        )
    for i in range(10):
        rows.append(
            _fill_row(
                (base + pd.Timedelta(days=2, hours=i)).isoformat(),
                px=100.0,
                sz=1.0,
                closed_pnl=-100.0 if i < 6 else 100.0,
                direction="Close Long",
            )
        )
    frame = pd.DataFrame(rows)
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    return frame.set_index("time").sort_index()


def _leaderboard_frame(rows: list[tuple[str, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "eth_address": addr,
                "account_value": account_value,
                "display_name": addr,
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
            for addr, account_value in rows
        ]
    )


def test_cli_runs_end_to_end_with_mocked_fetchers(mocker, tmp_path: Path) -> None:
    import scripts.build_academic_wallet_pool as builder

    leaderboard = _leaderboard_frame(
        [
            ("0xpass", 25_000.0),
            ("0xwhale", 500_000.0),
        ]
    )
    mocker.patch.object(builder, "fetch_leaderboard", return_value=leaderboard)

    def _fake_fetch(address: str, start, end):
        if address.lower() == "0xpass":
            return _retail_open_close_fills(25_000.0)
        return _retail_open_close_fills(500_000.0)

    mocker.patch.object(builder, "fetch_user_fills", side_effect=_fake_fetch)

    out_path = tmp_path / "academic_wallet_pool.parquet"
    result = builder.build_academic_wallet_pool(
        out=out_path,
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
        throttle_ms=0,
    )

    assert out_path.exists()
    written = pd.read_parquet(out_path)
    assert written["wallet"].tolist() == ["0xpass"]
    assert result["written_count"] == 1
    assert result["funnel"]["leaderboard"] == 2
    assert result["funnel"]["final"] == 1


def test_cli_honours_top_n_limit(mocker, tmp_path: Path) -> None:
    import scripts.build_academic_wallet_pool as builder

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
        return _retail_open_close_fills(25_000.0)

    mocker.patch.object(builder, "fetch_user_fills", side_effect=_fake_fetch)

    result = builder.build_academic_wallet_pool(
        out=tmp_path / "pool.parquet",
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
        top_n=2,
        throttle_ms=0,
    )

    assert len(fetched_addresses) == 2
    assert result["funnel"]["leaderboard"] == 2


def test_cli_logs_warning_when_fill_fetch_fails(mocker, tmp_path: Path, capsys) -> None:
    import scripts.build_academic_wallet_pool as builder

    leaderboard = _leaderboard_frame(
        [
            ("0xboom", 25_000.0),
            ("0xpass", 25_000.0),
        ]
    )
    mocker.patch.object(builder, "fetch_leaderboard", return_value=leaderboard)

    def _fake_fetch(address: str, start, end):
        if address == "0xboom":
            raise RuntimeError("network failure")
        return _retail_open_close_fills(25_000.0)

    mocker.patch.object(builder, "fetch_user_fills", side_effect=_fake_fetch)

    result = builder.build_academic_wallet_pool(
        out=tmp_path / "pool.parquet",
        as_of=pd.Timestamp("2026-05-26T00:00:00Z"),
        throttle_ms=0,
    )

    stderr = capsys.readouterr().err
    assert "warning" in stderr.lower()
    assert result["wallets_failed"] == 1
    assert result["written_count"] == 1


def test_cli_rejects_top_n_zero(mocker, capsys) -> None:
    import scripts.build_academic_wallet_pool as builder

    mocker.patch("sys.argv", ["build_academic_wallet_pool.py", "--top-n", "0"])

    with pytest.raises(SystemExit):
        builder._parse_args()

    assert "--top-n must be greater than 0" in capsys.readouterr().err


def test_cli_main_entrypoint_prints_summary(mocker, tmp_path: Path, capsys) -> None:
    import scripts.build_academic_wallet_pool as builder

    leaderboard = _leaderboard_frame([("0xpass", 25_000.0)])
    mocker.patch.object(builder, "fetch_leaderboard", return_value=leaderboard)
    mocker.patch.object(
        builder, "fetch_user_fills", return_value=_retail_open_close_fills(25_000.0)
    )

    out_path = tmp_path / "pool.parquet"
    mocker.patch(
        "sys.argv",
        [
            "build_academic_wallet_pool.py",
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
    assert "academic pool" in stdout.lower()
    assert "written" in stdout.lower()
    assert out_path.exists()
