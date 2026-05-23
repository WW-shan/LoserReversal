from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from scripts import run_wallet_walkforward as walkforward


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


def test_walkforward_split_fallback_logs_requested_and_effective_dimensions(mocker):
    logged = mocker.patch.object(walkforward, "_log")

    _, effective_n_splits, effective_min_train_days, effective_test_days = (
        walkforward._walk_forward_splits_with_fallback(
            start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end=datetime(2026, 3, 2, tzinfo=timezone.utc),
            n_splits=3,
            mode="expanding",
            min_train_days=120,
            test_days=30,
        )
    )

    assert (effective_n_splits, effective_min_train_days, effective_test_days) == (3, 30, 10)
    logged.assert_called_once_with(
        "[WARN] walk-forward fallback: requested "
        "(n_splits=3, min_train_days=120, test_days=30); using "
        "(n_splits=3, min_train_days=30, test_days=10)"
    )


def test_walkforward_report_shows_configured_effective_pairs_and_fallback_banner():
    report = walkforward._format_report(
        {
            "config": walkforward.WalkForwardConfig(
                n_splits=3,
                min_train_days=120,
                test_days=30,
                report=None,
            ),
            "effective_n_splits": 3,
            "effective_min_train_days": 30,
            "effective_test_days": 10,
            "data_span": {
                "start": pd.Timestamp("2026-01-01T00:00:00Z"),
                "end": pd.Timestamp("2026-03-02T00:00:00Z"),
                "total_days": 60,
                "n_fills": 100,
                "n_wallets_with_fills": 3,
                "n_failed_wallets": 0,
            },
            "split_results": [],
            "aggregate": {
                "oos_ir_mean": 0.0,
                "oos_ir_min": 0.0,
                "oos_n_trades_total": 0,
                "oos_max_dd_worst": 0.0,
                "is_oos_decay": 0.0,
            },
            "verdict": walkforward.Verdict("RED", "data_gap"),
        }
    )

    assert "## Verdict: RED\n> [WARN] walk-forward fallback used\nReason: data_gap" in report
    assert "- n_splits: 3 (effective: 3)" in report
    assert "- min_train_days: 120 (effective: 30)" in report
    assert "- test_days: 30 (effective: 10)" in report
    assert "- effective_splits:" not in report
    assert "- effective_test_days:" not in report


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
