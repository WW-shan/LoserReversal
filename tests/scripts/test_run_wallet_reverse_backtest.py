from __future__ import annotations

import math

import pandas as pd
import pytest

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


def _fills_with_time_column(rows: list[dict[str, object]]) -> pd.DataFrame:
    return _fills(rows).reset_index()


def _empty_fills() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "coin": pd.Series(dtype="object"),
            "side": pd.Series(dtype="object"),
            "dir": pd.Series(dtype="object"),
            "px": pd.Series(dtype="float64"),
            "sz": pd.Series(dtype="float64"),
            "start_position": pd.Series(dtype="float64"),
            "closed_pnl": pd.Series(dtype="float64"),
            "fee": pd.Series(dtype="float64"),
            "oid": pd.Series(dtype="int64"),
            "tid": pd.Series(dtype="int64"),
            "hash": pd.Series(dtype="object"),
            "crossed": pd.Series(dtype="bool"),
            "liquidation": pd.Series(dtype="bool"),
        },
        index=pd.DatetimeIndex([], tz="UTC", name="time"),
    )


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


def test_empty_wallets_exit_cleanly_with_all_zero_stats(mocker, tmp_path):
    mocker.patch.object(runner, "HyperliquidClient", return_value=object())
    mocker.patch.object(runner, "read_wallets", return_value=_wallets([]))

    result = runner.run_wallet_reverse_backtest(
        runner.WalletReverseBacktestConfig(
            top_wallet_n=50,
            report=tmp_path / "wallet_reverse_report.md",
        )
    )

    assert result["n_candidate_wallets"] == 0
    assert result["n_backtested_wallets"] == 0
    assert result["n_failed_wallets"] == 0
    assert result["n_skipped_wallets"] == 0
    assert result["per_wallet_stats"] == []
    assert result["portfolio_equity"].empty
    assert result["portfolio_stats"] == {
        "sharpe": 0.0,
        "daily_sharpe": 0.0,
        "trade_level_ir": 0.0,
        "sortino": 0.0,
        "max_dd": 0.0,
        "n_trades": 0,
        "win_rate": 0.0,
        "total_return": 0.0,
        "equity_final": 0.0,
        "capital_per_wallet": 10_000.0,
    }


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


def test_trade_level_ir_uses_net_trade_returns_and_annual_trade_frequency():
    trades = [
        {
            "entry_time": pd.Timestamp("2026-01-01T00:00:00Z"),
            "exit_time": pd.Timestamp("2026-01-02T00:00:00Z"),
            "return": 0.01,
        },
        {
            "entry_time": pd.Timestamp("2026-01-04T00:00:00Z"),
            "exit_time": pd.Timestamp("2026-01-05T00:00:00Z"),
            "return": 0.03,
        },
        {
            "entry_time": pd.Timestamp("2026-01-07T00:00:00Z"),
            "exit_time": pd.Timestamp("2026-01-08T00:00:00Z"),
            "return": -0.02,
        },
        {
            "entry_time": pd.Timestamp("2026-01-10T00:00:00Z"),
            "exit_time": pd.Timestamp("2026-01-11T00:00:00Z"),
            "return": 0.04,
        },
    ]
    returns = pd.Series([0.01, 0.03, -0.02, 0.04], dtype="float64")
    annual_trade_freq = len(returns) / 10 * 365
    expected = returns.mean() / returns.std(ddof=0) * math.sqrt(annual_trade_freq)

    assert runner._trade_level_ir(trades) == pytest.approx(expected)
    assert runner._trade_level_ir(trades[:1]) == 0.0


def test_skip_reason_bucket_counts_match_non_backtested_wallets(mocker, tmp_path):
    addresses = [
        "0xvalid",
        "0xnofills",
        "0xnodir",
        "0xnosize",
        "0xnocandle",
        "0xnopair",
        "0xnotime",
        "0xnocoin",
    ]
    mocker.patch.object(runner, "HyperliquidClient", return_value=object())
    mocker.patch.object(runner, "read_wallets", return_value=_wallets(addresses))
    fills_by_address = {
        "0xvalid": _fills([{"time": "2026-01-01T00:00:00Z", "coin": "BTC"}]),
        "0xnofills": _empty_fills(),
        "0xnodir": _fills(
            [
                {
                    "time": "2026-01-01T00:00:00Z",
                    "coin": "BTC",
                    "dir": "Close Long",
                }
            ]
        ),
        "0xnosize": _fills(
            [
                {
                    "time": "2026-01-01T00:00:00Z",
                    "coin": "BTC",
                    "px": 500.0,
                    "sz": 1.0,
                }
            ]
        ),
        "0xnocandle": _fills([{"time": "2026-01-01T00:00:00Z", "coin": "NOCANDLE"}]),
        "0xnopair": _fills([{"time": "2026-01-05T00:00:00Z", "coin": "NOPAIR"}]),
        "0xnotime": _fills_with_time_column([{"time": None, "coin": "BTC"}]),
        "0xnocoin": _fills([{"time": "2026-01-01T00:00:00Z", "coin": None}]),
    }
    mocker.patch.object(runner, "read_fills", side_effect=lambda address: fills_by_address[address])

    def load_candles(coin, _interval, _start, _end, _client):
        if coin == "NOCANDLE":
            raise FileNotFoundError("missing candles")
        if coin == "NOPAIR":
            index = pd.DatetimeIndex([pd.Timestamp("2026-01-05T00:00:00Z")], name="timestamp")
            close = pd.Series([100.0], index=index)
            return pd.DataFrame(
                {
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 1.0,
                },
                index=index,
            ), True
        return _candles(
            {
                "2026-01-01T00:00:00Z": 100.0,
                "2026-01-01T04:00:00Z": 104.0,
            }
        ), True

    mocker.patch.object(runner, "_load_or_fetch_candles", side_effect=load_candles)

    result = runner.run_wallet_reverse_backtest(
        runner.WalletReverseBacktestConfig(
            holding_hours=4,
            top_wallet_n=len(addresses),
            report=tmp_path / "wallet_reverse_report.md",
        )
    )

    funnel = result["funnel"]
    assert funnel["skip_no_fills"] == 1
    assert funnel["skip_no_open_dir"] == 1
    assert funnel["skip_no_retail_size"] == 1
    assert funnel["skip_no_candle"] == 1
    assert funnel["skip_no_qualifying_event"] == 3
    assert "skip_no_valid_pair" not in funnel
    skipped_total = sum(
        funnel[key]
        for key in [
            "skip_no_fills",
            "skip_no_open_dir",
            "skip_no_retail_size",
            "skip_no_candle",
            "skip_no_qualifying_event",
        ]
    )
    assert (
        result["n_candidate_wallets"] - result["n_backtested_wallets"] - result["n_failed_wallets"]
        == skipped_total
    )
    assert result["n_skipped_wallets"] == skipped_total

    report = (tmp_path / "wallet_reverse_report.md").read_text()
    assert "| skip_no_fills | 1 |" in report
    assert "| skip_no_open_dir | 1 |" in report
    assert "| skip_no_retail_size | 1 |" in report
    assert "| skip_no_candle | 1 |" in report
    assert "| skip_no_qualifying_event | 3 |" in report
    assert "skip_no_valid_pair" not in report
