from __future__ import annotations

import pandas as pd

from signals.unlock_grid import GridCell
from signals.unlock_walkforward import run_per_signal_walkforward, select_best_config


def test_select_best_config_with_fix_cohort_only_searches_min_pct(monkeypatch):
    grid_df = pd.DataFrame(
        [
            {"signal": "v2", "min_unlock_pct": 0.01, "cohort": "team"},
            {"signal": "v2", "min_unlock_pct": 0.02, "cohort": "team"},
            {"signal": "v2", "min_unlock_pct": 0.05, "cohort": "team"},
            {"signal": "v2", "min_unlock_pct": 0.01, "cohort": "team+investor"},
            {"signal": "v2", "min_unlock_pct": 0.02, "cohort": "team+investor"},
            {"signal": "v2", "min_unlock_pct": 0.01, "cohort": "all"},
        ]
    )
    visited_cells: list[tuple[float, str]] = []
    stats: dict[tuple[float, str], dict[str, float | int]] = {
        (0.01, "team"): {"n_trades": 10, "sharpe": 0.4},
        (0.02, "team"): {"n_trades": 12, "sharpe": 1.0},
        (0.05, "team"): {"n_trades": 6, "sharpe": 0.6},
        (0.01, "team+investor"): {"n_trades": 11, "sharpe": 3.0},
        (0.02, "team+investor"): {"n_trades": 12, "sharpe": 2.0},
        (0.01, "all"): {"n_trades": 15, "sharpe": 5.0},
    }

    def fake_run_cell(events, prices, coverage, cell, *, init_cash, fees, slippage):
        visited_cells.append((cell.min_unlock_pct, cell.cohort_name))
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

    cell = select_best_config(
        grid_df,
        "v2",
        _events(),
        {"ARB": _prices()},
        _coverage(),
        fix_cohort="team",
    )

    assert cell is not None
    assert cell.code == "v2"
    assert cell.cohort_name == "team"
    assert cell.min_unlock_pct == 0.02
    # IS search restricted to team cohort only
    visited_cohorts = {cohort for _, cohort in visited_cells}
    assert visited_cohorts == {"team"}
    # And only the three team min_pct cells were explored
    assert sorted(visited_cells) == sorted(
        [(0.01, "team"), (0.02, "team"), (0.05, "team")]
    )


def test_select_best_config_without_fix_cohort_searches_all_cohorts(monkeypatch):
    grid_df = pd.DataFrame(
        [
            {"signal": "v2", "min_unlock_pct": 0.01, "cohort": "team"},
            {"signal": "v2", "min_unlock_pct": 0.01, "cohort": "team+investor"},
            {"signal": "v2", "min_unlock_pct": 0.01, "cohort": "all"},
        ]
    )
    visited_cells: list[tuple[float, str]] = []

    def fake_run_cell(events, prices, coverage, cell, *, init_cash, fees, slippage):
        visited_cells.append((cell.min_unlock_pct, cell.cohort_name))
        return {
            "signal": cell.code,
            "min_unlock_pct": cell.min_unlock_pct,
            "cohort": cell.cohort_name,
            "n_trades": 10,
            "win_rate": 0.5,
            "sharpe": 1.0,
            "sortino": 1.0,
            "max_dd": -0.02,
            "total_return": 0.03,
            "mean_pnl": 1.0,
            "median_pnl": 1.0,
        }

    monkeypatch.setattr("signals.unlock_walkforward.run_cell", fake_run_cell)

    select_best_config(
        grid_df,
        "v2",
        _events(),
        {"ARB": _prices()},
        _coverage(),
    )

    visited_cohorts = {cohort for _, cohort in visited_cells}
    assert visited_cohorts == {"team", "team+investor", "all"}


def test_select_best_config_fix_cohort_returns_none_when_no_match(monkeypatch):
    grid_df = pd.DataFrame(
        [
            {"signal": "v2", "min_unlock_pct": 0.01, "cohort": "team+investor"},
            {"signal": "v2", "min_unlock_pct": 0.02, "cohort": "all"},
        ]
    )

    def fake_run_cell(events, prices, coverage, cell, *, init_cash, fees, slippage):
        return {
            "signal": cell.code,
            "min_unlock_pct": cell.min_unlock_pct,
            "cohort": cell.cohort_name,
            "n_trades": 10,
            "win_rate": 0.5,
            "sharpe": 1.0,
            "sortino": 1.0,
            "max_dd": -0.02,
            "total_return": 0.03,
            "mean_pnl": 1.0,
            "median_pnl": 1.0,
        }

    monkeypatch.setattr("signals.unlock_walkforward.run_cell", fake_run_cell)

    cell = select_best_config(
        grid_df,
        "v2",
        _events(),
        {"ARB": _prices()},
        _coverage(),
        fix_cohort="team",
    )

    assert cell is None


def test_run_per_signal_walkforward_threads_fix_cohort_to_selector(monkeypatch):
    splits = [_split("2026-01-01", "2026-02-01", "2026-02-01", "2026-03-01")]
    captured_fix_cohort: list[str | None] = []

    def fake_select_best_config(
        grid_df,
        signal_code,
        train_events,
        train_prices,
        train_coverage,
        min_n_trades=5,
        *,
        init_cash=None,
        fees=None,
        slippage=None,
        fix_cohort=None,
    ):
        captured_fix_cohort.append(fix_cohort)
        return _cell(signal_code, 0.02, "team")

    monkeypatch.setattr("signals.unlock_walkforward.select_best_config", fake_select_best_config)
    monkeypatch.setattr(
        "signals.unlock_walkforward.run_cell",
        lambda events, prices, coverage, cell, **kwargs: _stats(cell, n_trades=3, sharpe=1.0),
    )

    run_per_signal_walkforward(
        _events(),
        {"ARB": _prices()},
        _coverage(),
        splits,
        ["v2"],
        grid_df=_grid_df(),
        fix_cohort="team",
    )

    assert captured_fix_cohort == ["team"]


def test_run_per_signal_walkforward_fix_cohort_filters_fallback_candidates(monkeypatch):
    splits = [_split("2026-01-01", "2026-02-01", "2026-02-01", "2026-03-01")]
    grid_df = pd.DataFrame(
        [
            {"signal": "v2", "min_unlock_pct": 0.01, "cohort": "team"},
            {"signal": "v2", "min_unlock_pct": 0.02, "cohort": "team"},
            {"signal": "v2", "min_unlock_pct": 0.01, "cohort": "all"},
        ]
    )
    visited_cohorts: list[str] = []

    monkeypatch.setattr(
        "signals.unlock_walkforward.select_best_config",
        lambda *args, **kwargs: None,
    )

    def fake_run_cell(events, prices, coverage, cell, *, init_cash, fees, slippage, **kwargs):
        visited_cohorts.append(cell.cohort_name)
        return _stats(cell, n_trades=1, sharpe=0.5)

    monkeypatch.setattr("signals.unlock_walkforward.run_cell", fake_run_cell)

    run_per_signal_walkforward(
        _events(),
        {"ARB": _prices()},
        _coverage(),
        splits,
        ["v2"],
        grid_df=grid_df,
        fix_cohort="team",
    )

    # Fallback search must also be cohort-restricted
    assert set(visited_cohorts) == {"team"}


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
