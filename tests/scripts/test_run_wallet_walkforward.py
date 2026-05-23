from __future__ import annotations

import pandas as pd

from scripts import run_wallet_cluster_backtest as cluster_runner
from scripts import run_wallet_reverse_backtest as reverse_runner
from scripts import run_wallet_walkforward as walkforward


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


def test_walkforward_filter_pool_fills_uses_inclusive_start_exclusive_end():
    pool = {
        "0xaaa": _fills(
            [
                {"time": "2026-01-05T00:00:00Z", "tid": 1},
                {"time": "2026-01-10T00:00:00Z", "tid": 2},
                {"time": "2026-01-20T00:00:00Z", "tid": 3},
            ]
        )
    }

    filtered = walkforward._filter_pool_fills_by_date(
        pool,
        pd.Timestamp("2026-01-10T00:00:00Z"),
        pd.Timestamp("2026-01-20T00:00:00Z"),
    )

    assert list(filtered["0xaaa"].index) == [pd.Timestamp("2026-01-10T00:00:00Z")]


def test_walkforward_select_best_is_row_prefers_eligible_by_trade_level_ir():
    rows = [
        {"min_wallets": 3, "window_minutes": 15, "holding_hours": 1, "trade_level_ir": 0.5, "n_trades": 99},
        {"min_wallets": 5, "window_minutes": 30, "holding_hours": 4, "trade_level_ir": 1.1, "n_trades": 100},
        {"min_wallets": 7, "window_minutes": 60, "holding_hours": 12, "trade_level_ir": 1.4, "n_trades": 120},
    ]

    best_row, eligible_in_is, selection_mode = walkforward._select_best_is_row(rows)

    assert best_row["min_wallets"] == 7
    assert eligible_in_is is True
    assert selection_mode == "eligible"


def test_walkforward_select_best_is_row_uses_positive_trade_fallback_modes():
    median_rows = [
        {"min_wallets": 3, "window_minutes": 15, "holding_hours": 1, "trade_level_ir": 4.0, "n_trades": 1},
        {"min_wallets": 5, "window_minutes": 30, "holding_hours": 4, "trade_level_ir": 1.1, "n_trades": 4},
        {"min_wallets": 7, "window_minutes": 60, "holding_hours": 12, "trade_level_ir": 0.9, "n_trades": 4},
        {"min_wallets": 10, "window_minutes": 60, "holding_hours": 24, "trade_level_ir": -0.5, "n_trades": 5},
    ]
    any_rows = [
        {"min_wallets": 3, "window_minutes": 15, "holding_hours": 1, "trade_level_ir": 0.5, "n_trades": 1},
        {"min_wallets": 5, "window_minutes": 30, "holding_hours": 4, "trade_level_ir": -0.1, "n_trades": 2},
        {"min_wallets": 7, "window_minutes": 60, "holding_hours": 12, "trade_level_ir": -0.2, "n_trades": 10},
    ]
    zero_rows = [
        {"min_wallets": 3, "window_minutes": 15, "holding_hours": 1, "trade_level_ir": 0.0, "n_trades": 0},
        {"min_wallets": 5, "window_minutes": 30, "holding_hours": 4, "trade_level_ir": 1.0, "n_trades": 0},
    ]

    median_best, median_eligible, median_mode = walkforward._select_best_is_row(median_rows)
    any_best, any_eligible, any_mode = walkforward._select_best_is_row(any_rows)
    zero_best, zero_eligible, zero_mode = walkforward._select_best_is_row(zero_rows)

    assert median_best["min_wallets"] == 5
    assert median_eligible is False
    assert median_mode == "positive_trades_median"
    assert any_best["min_wallets"] == 3
    assert any_eligible is False
    assert any_mode == "positive_trades_any"
    assert zero_best["min_wallets"] == 5
    assert zero_eligible is False
    assert zero_mode == "zero_trade_fallback"


def test_walkforward_verdict_logic_for_green_yellow_and_red_reasons():
    assert walkforward._verdict(
        {"oos_ir_mean": 0.0, "oos_n_trades_total": 0, "oos_max_dd_worst": 0.0}
    ) == walkforward.Verdict("RED", "data_gap")
    assert walkforward._verdict(
        {"oos_ir_mean": 1.4, "oos_n_trades_total": 20, "oos_max_dd_worst": 0.0}
    ) == walkforward.Verdict("RED", "insufficient_sample")
    assert walkforward._verdict(
        {"oos_ir_mean": 1.4, "oos_n_trades_total": 100, "oos_max_dd_worst": -0.26}
    ) == walkforward.Verdict("RED", "max_drawdown_breach")
    assert walkforward._verdict(
        {"oos_ir_mean": 0.9, "oos_n_trades_total": 100, "oos_max_dd_worst": 0.0}
    ) == walkforward.Verdict("RED", "oos_ir_below_yellow")
    assert walkforward._verdict(
        {"oos_ir_mean": 1.0, "oos_n_trades_total": 100, "oos_max_dd_worst": 0.0}
    ) == walkforward.Verdict("YELLOW", "yellow_thresholds_met")
    assert walkforward._verdict(
        {"oos_ir_mean": 1.2, "oos_n_trades_total": 100, "oos_max_dd_worst": -0.25}
    ) == walkforward.Verdict("GREEN", "green_thresholds_met")


def test_walkforward_aggregate_rows_show_no_sample_status_for_zero_oos_trades():
    rows = walkforward._aggregate_rows(
        {
            "oos_ir_mean": 0.0,
            "oos_ir_min": 0.0,
            "oos_n_trades_total": 0,
            "oos_max_dd_worst": 0.0,
            "is_oos_decay": 0.0,
        }
    )

    assert rows == [
        "| OOS Trade-level IR (mean) | n/a | >= 1.2 (GREEN) / >= 1.0 (YELLOW) | NO SAMPLE |",
        "| OOS Trade-level IR (min/worst) | n/a | >= 0 desired | NO SAMPLE |",
        "| OOS n_trades (total) | 0 | >= 100 | FAIL |",
        "| OOS Max DD (worst) | n/a | >= -25% | NO SAMPLE |",
        f"| {walkforward.IS_OOS_DECAY_LABEL} | n/a | <= 30% desired | NO SAMPLE |",
    ]
