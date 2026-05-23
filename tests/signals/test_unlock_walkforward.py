from __future__ import annotations

import pandas as pd

from signals.unlock_walkforward import select_best_config


def test_select_best_config_returns_highest_sharpe_eligible(monkeypatch):
    grid_df = pd.DataFrame(
        [
            {"signal": "v1", "min_unlock_pct": 0.01, "cohort": "team"},
            {"signal": "v1", "min_unlock_pct": 0.02, "cohort": "team"},
            {"signal": "v1", "min_unlock_pct": 0.05, "cohort": "team"},
            {"signal": "v2", "min_unlock_pct": 0.01, "cohort": "team"},
        ]
    )
    stats = {
        (0.01, "team"): {"n_trades": 20, "sharpe": 0.7},
        (0.02, "team"): {"n_trades": 16, "sharpe": 1.4},
        (0.05, "team"): {"n_trades": 5, "sharpe": 9.0},
    }

    def fake_run_cell(events, prices, coverage, cell, *, init_cash, fees, slippage):
        row = stats[(cell.min_unlock_pct, cell.cohort_name)]
        return {
            "signal": cell.code,
            "min_unlock_pct": cell.min_unlock_pct,
            "cohort": cell.cohort_name,
            "n_trades": row["n_trades"],
            "win_rate": 0.5,
            "sharpe": row["sharpe"],
            "sortino": 1.0,
            "max_dd": -0.02,
            "total_return": 0.03,
            "mean_pnl": 1.0,
            "median_pnl": 1.0,
        }

    monkeypatch.setattr("signals.unlock_walkforward.run_cell", fake_run_cell)

    cell = select_best_config(grid_df, "v1", _events(), {"ARB": _prices()}, _coverage())

    assert cell is not None
    assert cell.code == "v1"
    assert cell.min_unlock_pct == 0.02
    assert cell.cohort_name == "team"


def test_select_best_config_returns_none_when_no_eligible(monkeypatch):
    grid_df = pd.DataFrame(
        [
            {"signal": "v1", "min_unlock_pct": 0.01, "cohort": "team"},
            {"signal": "v1", "min_unlock_pct": 0.02, "cohort": "team"},
        ]
    )

    def fake_run_cell(events, prices, coverage, cell, *, init_cash, fees, slippage):
        return {
            "signal": cell.code,
            "min_unlock_pct": cell.min_unlock_pct,
            "cohort": cell.cohort_name,
            "n_trades": 14,
            "win_rate": 0.5,
            "sharpe": 9.0,
            "sortino": 1.0,
            "max_dd": -0.02,
            "total_return": 0.03,
            "mean_pnl": 1.0,
            "median_pnl": 1.0,
        }

    monkeypatch.setattr("signals.unlock_walkforward.run_cell", fake_run_cell)

    cell = select_best_config(grid_df, "v1", _events(), {"ARB": _prices()}, _coverage())

    assert cell is None


def _events() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "token": "ARB",
                "coingecko_id": "arb",
                "unlock_date": pd.Timestamp("2026-01-05T00:00:00Z"),
                "unlock_pct": 0.05,
                "category": "insiders",
                "has_hl_perp": True,
                "vesting_type": "cliff",
            }
        ]
    )


def _coverage() -> pd.DataFrame:
    return pd.DataFrame(
        [{"token": "ARB", "unlock_date": "2026-01-05", "coverage_status": "ok"}]
    )


def _prices() -> pd.Series:
    index = pd.date_range("2025-12-01", periods=70, freq="1D", tz="UTC")
    return pd.Series(range(70), index=index, name="close", dtype="float64")
