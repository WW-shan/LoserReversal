from __future__ import annotations

import math

import pandas as pd

from scripts import run_wallet_reverse_backtest as runner


def _wallets(addresses: list[str]) -> pd.DataFrame:
    return pd.DataFrame({"eth_address": addresses})


def _fills(rows: list[dict[str, object]]) -> pd.DataFrame:
    defaults = {
        "coin": "BTC",
        "side": "B",
        "dir": "Open Short",
        "px": 100.0,
        "sz": 20.0,
        "start_position": 0.0,
        "closed_pnl": 0.0,
        "fee": 1.0,
        "oid": 1,
        "tid": 1,
        "hash": "0x1",
        "crossed": False,
        "liquidation": False,
    }
    frame = pd.DataFrame([{**defaults, **row} for row in rows])
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    return frame.set_index("time")


def _candles(points: dict[str, float]) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", "2026-01-04 08:00", freq="1h", tz="UTC")
    close = pd.Series(index=index, dtype="float64")
    for timestamp, value in points.items():
        close.loc[pd.Timestamp(timestamp)] = value
    close = close.interpolate(method="time").ffill().bfill()
    return pd.DataFrame(
        {
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": 1.0,
        },
        index=index,
    )


def test_synthetic_wallets_compute_hourly_sharpe_trade_level_ir_and_daily_sharpe(
    mocker,
    tmp_path,
):
    mocker.patch.object(runner, "HyperliquidClient", return_value=object())
    mocker.patch.object(runner, "read_wallets", return_value=_wallets(["0xaaa", "0xbbb"]))
    fills_by_address = {
        "0xaaa": _fills(
            [
                {"time": "2026-01-01T00:00:00Z", "coin": "BTC", "dir": "Open Short", "tid": 1},
                {"time": "2026-01-02T00:00:00Z", "coin": "BTC", "dir": "Open Long", "tid": 2},
                {"time": "2026-01-03T00:00:00Z", "coin": "BTC", "dir": "Open Short", "tid": 3},
            ]
        ),
        "0xbbb": _fills(
            [
                {
                    "time": "2026-01-01T06:00:00Z",
                    "coin": "ETH",
                    "dir": "Open Short",
                    "px": 50.0,
                    "sz": 40.0,
                    "tid": 4,
                },
                {
                    "time": "2026-01-02T06:00:00Z",
                    "coin": "ETH",
                    "dir": "Open Long",
                    "px": 60.0,
                    "sz": 40.0,
                    "tid": 5,
                },
                {
                    "time": "2026-01-03T06:00:00Z",
                    "coin": "ETH",
                    "dir": "Open Long",
                    "px": 55.0,
                    "sz": 40.0,
                    "tid": 6,
                },
            ]
        ),
    }
    mocker.patch.object(runner, "read_fills", side_effect=lambda address: fills_by_address[address])
    candles_by_coin = {
        "BTC": _candles(
            {
                "2026-01-01T00:00:00Z": 100.0,
                "2026-01-01T04:00:00Z": 104.0,
                "2026-01-02T00:00:00Z": 110.0,
                "2026-01-02T04:00:00Z": 105.0,
                "2026-01-03T00:00:00Z": 100.0,
                "2026-01-03T04:00:00Z": 97.0,
            }
        ),
        "ETH": _candles(
            {
                "2026-01-01T06:00:00Z": 50.0,
                "2026-01-01T10:00:00Z": 53.0,
                "2026-01-02T06:00:00Z": 60.0,
                "2026-01-02T10:00:00Z": 58.0,
                "2026-01-03T06:00:00Z": 55.0,
                "2026-01-03T10:00:00Z": 57.0,
            }
        ),
    }
    mocker.patch.object(
        runner,
        "_load_or_fetch_candles",
        side_effect=lambda coin, _interval, _start, _end, _client: (candles_by_coin[coin], True),
    )

    result = runner.run_wallet_reverse_backtest(
        runner.WalletReverseBacktestConfig(
            holding_hours=4,
            top_wallet_n=2,
            report=tmp_path / "wallet_reverse_report.md",
        )
    )

    stats = result["portfolio_stats"]
    assert stats["n_trades"] == 6
    assert math.isfinite(stats["sharpe"])
    assert math.isfinite(stats["trade_level_ir"])
    assert math.isfinite(stats["daily_sharpe"])
    assert stats["trade_level_ir"] != 0.0
    assert stats["daily_sharpe"] != 0.0
    assert all("trade_level_ir" in row for row in result["per_wallet_stats"])
    assert all("daily_sharpe" in row for row in result["per_wallet_stats"])

    report = (tmp_path / "wallet_reverse_report.md").read_text()
    assert "| Hourly Sharpe |" in report
    assert "| Trade-level IR |" in report
    assert "| Daily Sharpe |" in report
