from __future__ import annotations

import pandas as pd

from signals.unlock_grid import GridCell
from signals.unlock_walkforward import select_best_config
from signals.unlock_walkforward import run_per_signal_walkforward


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


def test_run_per_signal_walkforward_yields_one_row_per_signal_per_split(monkeypatch):
    splits = [
        _split("2026-01-01", "2026-02-01", "2026-02-01", "2026-03-01"),
        _split("2026-01-01", "2026-03-01", "2026-03-01", "2026-04-01"),
    ]

    def fake_select_best_config(
        grid_df,
        signal_code,
        train_events,
        train_prices,
        train_coverage,
        min_n_trades=15,
        **kwargs,
    ):
        return _cell(signal_code, 0.02, "team")

    def fake_run_cell(events, prices, coverage, cell, *, init_cash, fees, slippage):
        return _stats(cell, n_trades=3, sharpe=1.0)

    monkeypatch.setattr("signals.unlock_walkforward.select_best_config", fake_select_best_config)
    monkeypatch.setattr("signals.unlock_walkforward.run_cell", fake_run_cell)

    result = run_per_signal_walkforward(
        _events(),
        {"ARB": _prices()},
        _coverage(),
        splits,
        ["v1", "v2"],
        grid_df=_grid_df(),
    )

    split_rows = result.loc[result["split_idx"] >= 0]
    assert len(split_rows) == 4
    assert split_rows[["signal", "split_idx"]].to_records(index=False).tolist() == [
        ("v1", 0),
        ("v2", 0),
        ("v1", 1),
        ("v2", 1),
    ]
    assert set(split_rows["kind"]) == {"per_signal"}


def test_run_per_signal_walkforward_includes_aggregate_row(monkeypatch):
    splits = [
        _split("2026-01-01", "2026-02-01", "2026-02-01", "2026-03-01"),
        _split("2026-01-01", "2026-03-01", "2026-03-01", "2026-04-01"),
    ]
    fold_stats = [
        {"n_trades": 10, "win_rate": 0.50, "sharpe": 0.8, "max_dd": -0.02},
        {"n_trades": 30, "win_rate": 0.75, "sharpe": 1.2, "max_dd": -0.05},
    ]

    monkeypatch.setattr(
        "signals.unlock_walkforward.select_best_config",
        lambda *args, **kwargs: _cell("v1", 0.02, "team"),
    )

    def fake_run_cell(events, prices, coverage, cell, *, init_cash, fees, slippage):
        row = fold_stats.pop(0)
        return _stats(
            cell,
            n_trades=row["n_trades"],
            win_rate=row["win_rate"],
            sharpe=row["sharpe"],
            max_dd=row["max_dd"],
        )

    monkeypatch.setattr("signals.unlock_walkforward.run_cell", fake_run_cell)

    result = run_per_signal_walkforward(
        _events(),
        {"ARB": _prices()},
        _coverage(),
        splits,
        ["v1"],
        grid_df=_grid_df(),
    )

    aggregate = result.loc[result["split_idx"].eq(-1)].iloc[0]
    assert aggregate["signal"] == "v1"
    assert aggregate["n_trades"] == 40
    assert aggregate["sharpe"] == 1.0
    assert aggregate["win_rate"] == 0.6875
    assert aggregate["max_dd"] == -0.05


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


def _grid_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"signal": "v1", "min_unlock_pct": 0.02, "cohort": "team"},
            {"signal": "v2", "min_unlock_pct": 0.02, "cohort": "team"},
        ]
    )


def _split(
    train_start: str,
    train_end: str,
    test_start: str,
    test_end: str,
) -> tuple[tuple[pd.Timestamp, pd.Timestamp], tuple[pd.Timestamp, pd.Timestamp]]:
    return (
        (pd.Timestamp(train_start, tz="UTC"), pd.Timestamp(train_end, tz="UTC")),
        (pd.Timestamp(test_start, tz="UTC"), pd.Timestamp(test_end, tz="UTC")),
    )


def _cell(signal: str, min_unlock_pct: float, cohort: str) -> GridCell:
    return GridCell(
        code=signal,
        min_unlock_pct=min_unlock_pct,
        cohort_name=cohort,
        signal_fn=lambda *args, **kwargs: {},
        direction="short",
        category_filter=None,
    )


def _stats(
    cell: GridCell,
    *,
    n_trades: int,
    win_rate: float = 0.5,
    sharpe: float,
    max_dd: float = -0.02,
) -> dict:
    return {
        "signal": cell.code,
        "min_unlock_pct": cell.min_unlock_pct,
        "cohort": cell.cohort_name,
        "n_trades": n_trades,
        "win_rate": win_rate,
        "sharpe": sharpe,
        "sortino": sharpe + 0.5,
        "max_dd": max_dd,
        "total_return": 0.03,
        "mean_pnl": 1.0,
        "median_pnl": 1.0,
    }
