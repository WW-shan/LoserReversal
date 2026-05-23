from __future__ import annotations

import pandas as pd

from scripts import run_wallet_cluster_backtest as cluster_runner
from scripts import run_wallet_reverse_backtest as reverse_runner


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


def test_run_wallet_reverse_backtest_filters_fills_by_date_window_exclusive_end(
    mocker,
    tmp_path,
):
    fills = _fills(
        [
            {"time": "2026-01-05T00:00:00Z", "tid": 1},
            {"time": "2026-01-15T00:00:00Z", "tid": 2},
            {"time": "2026-01-20T00:00:00Z", "tid": 3},
            {"time": "2026-01-25T00:00:00Z", "tid": 4},
        ]
    )
    captured_events: list[pd.DataFrame] = []

    mocker.patch.object(reverse_runner, "HyperliquidClient", return_value=object())
    mocker.patch.object(reverse_runner, "read_wallets", return_value=_wallets(["0xaaa"]))
    mocker.patch.object(reverse_runner, "read_fills", return_value=fills)

    def fake_backtest_wallet(address, events, config, freq, client):
        captured_events.append(events.copy())
        equity = pd.Series(
            [10_000.0, 10_000.0],
            index=pd.date_range("2026-01-01", periods=2, freq="1h", tz="UTC"),
            name=address,
        )
        return {
            "n_backtested_coins": 1,
            "events_with_candles": len(events),
            "stats": {
                "wallet": address,
                "sharpe": 0.0,
                "daily_sharpe": 0.0,
                "trade_level_ir": 0.0,
                "sortino": 0.0,
                "max_dd": 0.0,
                "n_trades": len(events),
                "win_rate": 0.0,
                "total_return": 0.0,
                "equity_final": 10_000.0,
                "trades_won": 0,
                "n_coins": 1,
            },
            "equity": equity,
            "trades": [],
        }

    mocker.patch.object(reverse_runner, "_backtest_wallet", side_effect=fake_backtest_wallet)

    train_result = reverse_runner.run_wallet_reverse_backtest(
        reverse_runner.WalletReverseBacktestConfig(
            report=tmp_path / "train.md",
            date_start=pd.Timestamp("2026-01-10T00:00:00Z"),
            date_end=pd.Timestamp("2026-01-20T00:00:00Z"),
        )
    )
    oos_result = reverse_runner.run_wallet_reverse_backtest(
        reverse_runner.WalletReverseBacktestConfig(
            report=tmp_path / "oos.md",
            date_start=pd.Timestamp("2026-01-20T00:00:00Z"),
            date_end=pd.Timestamp("2026-01-25T00:00:00Z"),
        )
    )

    assert list(captured_events[0]["entry_time"]) == [
        pd.Timestamp("2026-01-15T00:00:00Z")
    ]
    assert list(captured_events[1]["entry_time"]) == [
        pd.Timestamp("2026-01-20T00:00:00Z")
    ]
    assert train_result["funnel"]["date_start_fills"] == 3
    assert train_result["funnel"]["date_end_fills"] == 1
    assert oos_result["funnel"]["date_start_fills"] == 2
    assert oos_result["funnel"]["date_end_fills"] == 1


def test_wallet_reverse_date_end_filter_description_documents_exclusive_end():
    config = reverse_runner.WalletReverseBacktestConfig(
        report=None,
        date_start=pd.Timestamp("2026-01-10T00:00:00Z"),
        date_end=pd.Timestamp("2026-01-20T00:00:00Z"),
    )

    assert reverse_runner._date_end_filter(config) == "fill_time < 2026-01-20"


def test_run_wallet_cluster_backtest_runs_single_config_on_synthetic_cluster(
    mocker,
    tmp_path,
):
    mocker.patch.object(cluster_runner, "HyperliquidClient", return_value=object())
    mocker.patch.object(cluster_runner, "read_wallets", return_value=_wallets(["0x1", "0x2", "0x3"]))
    fills_by_address = {
        "0x1": _fills([{"time": "2026-01-01T00:00:00Z"}]),
        "0x2": _fills([{"time": "2026-01-01T00:10:00Z"}]),
        "0x3": _fills([{"time": "2026-01-01T00:20:00Z"}]),
    }
    mocker.patch.object(
        cluster_runner,
        "read_fills",
        side_effect=lambda address: fills_by_address[address],
    )
    mocker.patch.object(
        cluster_runner,
        "_load_or_fetch_candles",
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

    result = cluster_runner.run_wallet_cluster_backtest(
        cluster_runner.WalletClusterBacktestConfig(
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
