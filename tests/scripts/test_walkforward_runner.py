from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from scripts import run_unlock_backtest as runner
from scripts import run_unlock_walkforward as walkforward


def test_verdict_distinguishes_zero_and_small_oos_samples():
    zero_trades = {
        "oos_sharpe_mean": 0.0,
        "oos_n_trades_total": 0,
        "oos_max_dd_worst": 0.0,
    }
    small_sample = {
        "oos_sharpe_mean": 1.2,
        "oos_n_trades_total": 14,
        "oos_max_dd_worst": 0.0,
    }
    failed_thresholds = {
        "oos_sharpe_mean": 0.2,
        "oos_n_trades_total": 15,
        "oos_max_dd_worst": 0.0,
    }

    assert walkforward._verdict(zero_trades).reason == "data_gap"
    assert walkforward._verdict(small_sample).reason == "insufficient_sample"
    assert walkforward._verdict(failed_thresholds).reason == "thresholds_not_met"


def test_zero_trade_aggregate_rows_show_no_sample_status():
    rows = walkforward._aggregate_rows(
        {
            "oos_sharpe_mean": 0.0,
            "oos_sharpe_min": 0.0,
            "oos_n_trades_total": 0,
            "oos_max_dd_worst": 0.0,
            "is_oos_decay": 0.0,
        }
    )

    assert rows == [
        "| OOS Sharpe (mean) | n/a | >= 0.7 (GREEN) / >= 0.3 (YELLOW) | NO SAMPLE |",
        "| OOS Sharpe (min/worst) | n/a | >= 0 desired | NO SAMPLE |",
        "| OOS n_trades (total) | 0 | >= 30 (GREEN) / >= 15 (YELLOW) | FAIL |",
        "| OOS Max DD (worst) | n/a | >= -25% (GREEN) / >= -30% (YELLOW) | NO SAMPLE |",
        f"| {walkforward.IS_OOS_DECAY_LABEL} | n/a | <= 30% desired | NO SAMPLE |",
    ]


def test_select_best_is_row_prefers_positive_trade_median_bucket():
    rows = [
        {"pre_window": 3, "min_pct": 0.01, "sharpe": 4.0, "n_trades": 1},
        {"pre_window": 5, "min_pct": 0.01, "sharpe": 1.1, "n_trades": 4},
        {"pre_window": 7, "min_pct": 0.01, "sharpe": 0.9, "n_trades": 4},
        {"pre_window": 10, "min_pct": 0.01, "sharpe": -0.5, "n_trades": 5},
    ]

    best_row, eligible_in_is, selection_mode = walkforward._select_best_is_row(rows, 2)

    assert best_row["pre_window"] == 5
    assert eligible_in_is is False
    assert selection_mode == "positive_trades_median"


def test_select_best_is_row_reports_zero_trade_fallback(capsys):
    rows = [
        {"pre_window": 3, "min_pct": 0.01, "sharpe": 0.0, "n_trades": 0},
        {"pre_window": 5, "min_pct": 0.01, "sharpe": 1.0, "n_trades": 0},
    ]

    best_row, eligible_in_is, selection_mode = walkforward._select_best_is_row(rows, 2)

    assert best_row["pre_window"] == 5
    assert eligible_in_is is False
    assert selection_mode == "zero_trade_fallback"
    assert (
        "[WARN] split 2: no positive-trade IS config; fallback chose 0-trade max-Sharpe"
        in capsys.readouterr().err
    )


def test_run_unlock_backtest_filters_events_by_date_window_exclusive_end(monkeypatch):
    events = pd.DataFrame(
        [
            {
                "token": "ARB",
                "coingecko_id": "arb",
                "unlock_date": pd.Timestamp("2026-01-05T00:00:00Z"),
                "unlock_pct": 0.05,
                "category": "team",
                "has_hl_perp": True,
            },
            {
                "token": "ARB",
                "coingecko_id": "arb",
                "unlock_date": pd.Timestamp("2026-01-15T00:00:00Z"),
                "unlock_pct": 0.05,
                "category": "team",
                "has_hl_perp": True,
            },
            {
                "token": "ARB",
                "coingecko_id": "arb",
                "unlock_date": pd.Timestamp("2026-01-20T00:00:00Z"),
                "unlock_pct": 0.05,
                "category": "team",
                "has_hl_perp": True,
            },
            {
                "token": "ARB",
                "coingecko_id": "arb",
                "unlock_date": pd.Timestamp("2026-01-25T00:00:00Z"),
                "unlock_pct": 0.05,
                "category": "team",
                "has_hl_perp": True,
            },
        ]
    )
    captured_events: list[pd.DataFrame] = []

    monkeypatch.setattr(runner, "read_unlocks", lambda: events)
    monkeypatch.setattr(runner, "HyperliquidClient", lambda: object())

    def fake_load_or_fetch_candles(token, interval, start, end, client):
        index = pd.date_range(start, end, freq="1D", tz="UTC")
        candles = pd.DataFrame({"close": range(len(index))}, index=index)
        return candles, True

    def fake_unlock_short_signal(events_arg, prices, **kwargs):
        captured_events.append(events_arg.copy())
        index = next(iter(prices.values())).index
        series = pd.Series(False, index=index, dtype=bool)
        return {"ARB": (series, series)}

    def fake_run_backtest(prices, entries, exits, config):
        index = prices.index
        equity = pd.Series([10_000.0, 10_000.0], index=index[:2], name="equity")
        return SimpleNamespace(
            stats={
                "n_trades": 0,
                "sharpe": 0.0,
                "sortino": 0.0,
                "max_dd": 0.0,
                "total_return": 0.0,
                "win_rate": 0.0,
            },
            equity=equity,
        )

    monkeypatch.setattr(runner, "_load_or_fetch_candles", fake_load_or_fetch_candles)
    monkeypatch.setattr(runner, "unlock_short_signal", fake_unlock_short_signal)
    monkeypatch.setattr(runner, "run_backtest", fake_run_backtest)

    train_result = runner.run_unlock_backtest(
        runner.UnlockBacktestConfig(
            report=None,
            date_start=pd.Timestamp("2026-01-10T00:00:00Z"),
            date_end=pd.Timestamp("2026-01-20T00:00:00Z"),
        )
    )
    oos_result = runner.run_unlock_backtest(
        runner.UnlockBacktestConfig(
            report=None,
            date_start=pd.Timestamp("2026-01-20T00:00:00Z"),
            date_end=pd.Timestamp("2026-01-25T00:00:00Z"),
        )
    )

    assert list(captured_events[0]["unlock_date"]) == [
        pd.Timestamp("2026-01-15T00:00:00Z")
    ]
    assert list(captured_events[1]["unlock_date"]) == [
        pd.Timestamp("2026-01-20T00:00:00Z")
    ]
    assert train_result["funnel"]["date_start_events"] == 3
    assert train_result["funnel"]["date_end_events"] == 1
    assert oos_result["funnel"]["date_start_events"] == 2
    assert oos_result["funnel"]["date_end_events"] == 1


def test_split_rows_include_selection_mode():
    rows = walkforward._split_rows(
        [
            {
                "split": 1,
                "is_start": pd.Timestamp("2026-01-01T00:00:00Z"),
                "is_end": pd.Timestamp("2026-02-01T00:00:00Z"),
                "oos_start": pd.Timestamp("2026-02-01T00:00:00Z"),
                "oos_end": pd.Timestamp("2026-03-01T00:00:00Z"),
                "is_best_config": "pre=5 min=0.01",
                "is_sharpe": 1.1,
                "is_n_trades": 4,
                "oos_sharpe": 0.0,
                "oos_n_trades": 0,
                "oos_max_dd": 0.0,
                "eligible_in_is": False,
                "is_selection_mode": "positive_trades_median",
            }
        ]
    )

    assert rows == [
        "| 1 | 2026-01-01 | 2026-02-01 | 2026-02-01 | 2026-03-01 | "
        "pre=5 min=0.01 | 1.10 | 4 | n/a | 0 | n/a | no | positive_trades_median |"
    ]


def test_date_end_filter_description_documents_exclusive_end():
    config = runner.UnlockBacktestConfig(
        report=None,
        date_start=pd.Timestamp("2026-01-10T00:00:00Z"),
        date_end=pd.Timestamp("2026-01-20T00:00:00Z"),
    )

    assert runner._date_end_filter(config) == "unlock_date < 2026-01-20"
