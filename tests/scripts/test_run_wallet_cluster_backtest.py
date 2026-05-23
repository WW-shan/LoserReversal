from __future__ import annotations

import pandas as pd

from scripts import run_wallet_cluster_backtest as runner


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
    index = pd.date_range("2026-01-01", "2026-01-02", freq="1h", tz="UTC")
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


def test_run_wallet_cluster_backtest_runs_single_config_on_synthetic_cluster(
    mocker,
    tmp_path,
):
    mocker.patch.object(runner, "HyperliquidClient", return_value=object())
    mocker.patch.object(runner, "read_wallets", return_value=_wallets(["0x1", "0x2", "0x3"]))
    fills_by_address = {
        "0x1": _fills([{"time": "2026-01-01T00:00:00Z"}]),
        "0x2": _fills([{"time": "2026-01-01T00:10:00Z"}]),
        "0x3": _fills([{"time": "2026-01-01T00:20:00Z"}]),
    }
    mocker.patch.object(
        runner,
        "read_fills",
        side_effect=lambda address: fills_by_address[address],
    )
    mocker.patch.object(
        runner,
        "load_or_fetch_candles",
        return_value=(
            _candles(
                {
                    "2026-01-01T00:00:00Z": 100.0,
                    "2026-01-01T00:20:00Z": 100.0,
                    "2026-01-01T04:20:00Z": 95.0,
                }
            ),
            True,
        ),
    )

    result = runner.run_wallet_cluster_backtest(
        runner.WalletClusterBacktestConfig(
            min_wallets=3,
            window_minutes=30,
            holding_hours=4,
            top_wallet_n=3,
            report=tmp_path / "cluster.md",
        )
    )

    assert result["n_cluster_events"] == 1
    assert result["portfolio_stats"]["n_trades"] == 1
    assert result["funnel"]["cluster_events"] == 1
