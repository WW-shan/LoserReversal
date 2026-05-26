from __future__ import annotations

import pandas as pd

from scripts import run_bot_reverse_signal as runner


def _bot_pool(rows: list[tuple[str, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        [{"wallet": wallet, "bot_score": score} for wallet, score in rows]
    )


def _fills(
    rows: list[dict[str, object]],
) -> pd.DataFrame:
    defaults = {
        "coin": "BTC",
        "side": "B",
        "dir": "Open Long",
        "px": 100.0,
        "sz": 1.0,
        "start_position": 0.0,
        "closed_pnl": 0.0,
        "fee": 0.0,
        "oid": 1,
        "tid": 1,
        "hash": "0x1",
        "crossed": False,
        "liquidation": False,
    }
    frame = pd.DataFrame([{**defaults, **row} for row in rows])
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    return frame


def _candles(points: dict[str, float]) -> pd.DataFrame:
    index = pd.date_range("2026-01-01T00:00:00Z", periods=49, freq="1h")
    close = pd.Series(index=index, dtype="float64")
    for timestamp, value in points.items():
        close.loc[pd.Timestamp(timestamp)] = value
    close = close.interpolate(method="time").ffill().bfill()
    return pd.DataFrame(
        {
            "timestamp": close.index,
            "open": close.values,
            "high": close.values,
            "low": close.values,
            "close": close.values,
            "volume": 1.0,
        }
    )


def _write_bot_pool(path, rows: list[tuple[str, float]]) -> None:
    _bot_pool(rows).to_parquet(path, index=False)


def _write_fills(path, rows: list[dict[str, object]]) -> None:
    _fills(rows).to_parquet(path, index=False)


def _write_candles(path, points: dict[str, float]) -> None:
    _candles(points).to_parquet(path, index=False)


def test_cli_writes_reverse_signal_parquet_and_summary(mocker, tmp_path, capsys) -> None:
    bot_pool_path = tmp_path / "bot_wallets.parquet"
    fills_dir = tmp_path / "fills"
    candles_dir = tmp_path / "candles"
    out_path = tmp_path / "bot_reverse_signal.parquet"
    fills_dir.mkdir()
    candles_dir.mkdir()

    _write_bot_pool(
        bot_pool_path,
        [
            ("0x1", 0.9),
            ("0x2", 0.9),
            ("0x3", 0.9),
        ],
    )
    for wallet, time in [
        ("0x1", "2026-01-01T00:00:00Z"),
        ("0x2", "2026-01-01T00:10:00Z"),
        ("0x3", "2026-01-01T00:20:00Z"),
    ]:
        _write_fills(
            fills_dir / f"{wallet}.parquet",
            [{"time": time, "coin": "BTC", "dir": "Open Long"}],
        )
    _write_candles(
        candles_dir / "BTC_1h.parquet",
        {
            "2026-01-01T00:00:00Z": 100.0,
            "2026-01-01T01:00:00Z": 100.0,
            "2026-01-02T01:00:00Z": 100.0,
        },
    )
    mocker.patch(
        "sys.argv",
        [
            "run_bot_reverse_signal.py",
            "--bot-pool",
            str(bot_pool_path),
            "--fills-dir",
            str(fills_dir),
            "--candles-dir",
            str(candles_dir),
            "--out",
            str(out_path),
        ],
    )

    exit_code = runner.main()

    assert exit_code == 0
    stdout = capsys.readouterr().out
    assert "bot reverse" in stdout.lower()
    written = pd.read_parquet(out_path)
    assert written[["coin", "direction", "entry", "exit"]].to_dict("records") == [
        {"coin": "BTC", "direction": "short", "entry": True, "exit": False},
        {"coin": "BTC", "direction": "short", "entry": False, "exit": True},
    ]


def test_cli_ignores_wallets_below_bot_score_threshold(mocker, tmp_path) -> None:
    bot_pool_path = tmp_path / "bot_wallets.parquet"
    fills_dir = tmp_path / "fills"
    candles_dir = tmp_path / "candles"
    out_path = tmp_path / "bot_reverse_signal.parquet"
    fills_dir.mkdir()
    candles_dir.mkdir()

    _write_bot_pool(
        bot_pool_path,
        [
            ("0x1", 0.9),
            ("0x2", 0.9),
            ("0x3", 0.69),
        ],
    )
    for wallet, time in [
        ("0x1", "2026-01-01T00:00:00Z"),
        ("0x2", "2026-01-01T00:10:00Z"),
        ("0x3", "2026-01-01T00:20:00Z"),
    ]:
        _write_fills(
            fills_dir / f"{wallet}.parquet",
            [{"time": time, "coin": "BTC", "dir": "Open Long"}],
        )
    _write_candles(candles_dir / "BTC_1h.parquet", {"2026-01-01T00:00:00Z": 100.0})
    mocker.patch(
        "sys.argv",
        [
            "run_bot_reverse_signal.py",
            "--bot-pool",
            str(bot_pool_path),
            "--fills-dir",
            str(fills_dir),
            "--candles-dir",
            str(candles_dir),
            "--out",
            str(out_path),
        ],
    )

    runner.main()

    written = pd.read_parquet(out_path)
    assert written.empty


def test_cli_handles_multiple_coins_independently(mocker, tmp_path) -> None:
    bot_pool_path = tmp_path / "bot_wallets.parquet"
    fills_dir = tmp_path / "fills"
    candles_dir = tmp_path / "candles"
    out_path = tmp_path / "bot_reverse_signal.parquet"
    fills_dir.mkdir()
    candles_dir.mkdir()

    _write_bot_pool(
        bot_pool_path,
        [
            ("0x1", 0.9),
            ("0x2", 0.9),
            ("0x3", 0.9),
        ],
    )
    _write_fills(
        fills_dir / "0x1.parquet",
        [
            {"time": "2026-01-01T00:00:00Z", "coin": "BTC", "dir": "Open Long"},
            {"time": "2026-01-01T01:00:00Z", "coin": "ETH", "dir": "Open Short"},
        ],
    )
    _write_fills(
        fills_dir / "0x2.parquet",
        [
            {"time": "2026-01-01T00:10:00Z", "coin": "BTC", "dir": "Open Long"},
            {"time": "2026-01-01T01:10:00Z", "coin": "ETH", "dir": "Open Short"},
        ],
    )
    _write_fills(
        fills_dir / "0x3.parquet",
        [
            {"time": "2026-01-01T00:20:00Z", "coin": "BTC", "dir": "Open Long"},
            {"time": "2026-01-01T01:20:00Z", "coin": "ETH", "dir": "Open Short"},
        ],
    )
    _write_candles(
        candles_dir / "BTC_1h.parquet",
        {
            "2026-01-01T00:00:00Z": 100.0,
            "2026-01-01T01:00:00Z": 100.0,
            "2026-01-02T01:00:00Z": 100.0,
        },
    )
    _write_candles(
        candles_dir / "ETH_1h.parquet",
        {
            "2026-01-01T00:00:00Z": 50.0,
            "2026-01-01T02:00:00Z": 50.0,
            "2026-01-02T02:00:00Z": 50.0,
        },
    )
    mocker.patch(
        "sys.argv",
        [
            "run_bot_reverse_signal.py",
            "--bot-pool",
            str(bot_pool_path),
            "--fills-dir",
            str(fills_dir),
            "--candles-dir",
            str(candles_dir),
            "--out",
            str(out_path),
        ],
    )

    runner.main()

    written = pd.read_parquet(out_path)
    assert written["coin"].tolist() == ["BTC", "BTC", "ETH", "ETH"]
    assert written["direction"].tolist() == ["short", "short", "long", "long"]
