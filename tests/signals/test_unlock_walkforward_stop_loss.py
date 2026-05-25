from __future__ import annotations

import pandas as pd

from signals.unlock_grid import GridCell
from signals.unlock_walkforward import (
    compose_portfolio,
    run_per_signal_walkforward,
    select_best_config,
)


def test_select_best_config_forwards_stop_loss_to_run_cell(monkeypatch):
    grid_df = pd.DataFrame(
        [{"signal": "v2", "min_unlock_pct": 0.02, "cohort": "team"}]
    )
    captured: list[float | None] = []

    def fake_run_cell(events, prices, coverage, cell, **kwargs):
        captured.append(kwargs.get("stop_loss"))
        return _stats(cell, n_trades=5, sharpe=0.6)

    monkeypatch.setattr("signals.unlock_walkforward.run_cell", fake_run_cell)

    select_best_config(
        grid_df,
        "v2",
        _events(),
        {"ARB": _prices()},
        _coverage(),
        stop_loss=0.10,
    )

    assert captured == [0.10]


def test_select_best_config_without_stop_loss_does_not_pass_stop_kwarg(monkeypatch):
    grid_df = pd.DataFrame(
        [{"signal": "v2", "min_unlock_pct": 0.02, "cohort": "team"}]
    )
    captured: list[dict[str, object]] = []

    def fake_run_cell(events, prices, coverage, cell, **kwargs):
        captured.append(dict(kwargs))
        return _stats(cell, n_trades=5, sharpe=0.6)

    monkeypatch.setattr("signals.unlock_walkforward.run_cell", fake_run_cell)

    select_best_config(grid_df, "v2", _events(), {"ARB": _prices()}, _coverage())

    # No stop_loss requested -> kwarg omitted entirely so legacy callers/mocks
    # that pin (init_cash, fees, slippage) keep working.
    assert "stop_loss" not in captured[0]


def test_run_per_signal_walkforward_threads_stop_loss_to_run_cell(monkeypatch):
    splits = [_split("2026-01-01", "2026-02-01", "2026-02-01", "2026-03-01")]
    captured_stop_loss: list[float | None] = []

    monkeypatch.setattr(
        "signals.unlock_walkforward.select_best_config",
        lambda *args, **kwargs: _cell("v2", 0.02, "team"),
    )

    def fake_run_cell(events, prices, coverage, cell, **kwargs):
        captured_stop_loss.append(kwargs.get("stop_loss"))
        return _stats(cell, n_trades=3, sharpe=0.5)

    monkeypatch.setattr("signals.unlock_walkforward.run_cell", fake_run_cell)

    run_per_signal_walkforward(
        _events(),
        {"ARB": _prices()},
        _coverage(),
        splits,
        ["v2"],
        grid_df=_grid_df(),
        stop_loss=0.10,
    )

    assert captured_stop_loss == [0.10]


def test_compose_portfolio_threads_stop_loss_to_run_cell(monkeypatch):
    splits = [_split("2026-01-01", "2026-02-01", "2026-02-01", "2026-03-01")]
    captured_stop_loss: list[float | None] = []

    def fake_run_cell(events, prices, coverage, cell, **kwargs):
        captured_stop_loss.append(kwargs.get("stop_loss"))
        return _stats(cell, n_trades=3, sharpe=0.5)

    monkeypatch.setattr("signals.unlock_walkforward.run_cell", fake_run_cell)

    per_signal = pd.DataFrame(
        [
            {
                "kind": "per_signal",
                "signal": "v2",
                "split_idx": 0,
                "selected_min_pct": 0.02,
                "selected_cohort": "team",
                "n_trades": 5,
                "sharpe": 0.7,
                "sortino": 0.8,
                "win_rate": 0.6,
                "max_dd": -0.05,
                "total_return": 0.1,
                "fallback_used": False,
            },
            {
                "kind": "per_signal",
                "signal": "v2",
                "split_idx": -1,
                "selected_min_pct": float("nan"),
                "selected_cohort": "aggregate",
                "n_trades": 5,
                "sharpe": 0.7,
                "sortino": 0.8,
                "win_rate": 0.6,
                "max_dd": -0.05,
                "total_return": 0.1,
                "fallback_used": False,
            },
        ]
    )

    compose_portfolio(
        per_signal,
        _events(),
        {"ARB": _prices()},
        _coverage(),
        splits,
        top_k=1,
        stop_loss=0.10,
    )

    assert captured_stop_loss == [0.10]


def test_run_per_signal_walkforward_without_stop_loss_omits_kwarg(monkeypatch):
    """Legacy default keeps stop_loss out of run_cell kwargs entirely."""
    splits = [_split("2026-01-01", "2026-02-01", "2026-02-01", "2026-03-01")]
    captured: list[dict[str, object]] = []

    monkeypatch.setattr(
        "signals.unlock_walkforward.select_best_config",
        lambda *args, **kwargs: _cell("v2", 0.02, "team"),
    )

    def fake_run_cell(events, prices, coverage, cell, **kwargs):
        captured.append(dict(kwargs))
        return _stats(cell, n_trades=3, sharpe=0.5)

    monkeypatch.setattr("signals.unlock_walkforward.run_cell", fake_run_cell)

    run_per_signal_walkforward(
        _events(),
        {"ARB": _prices()},
        _coverage(),
        splits,
        ["v2"],
        grid_df=_grid_df(),
    )

    assert "stop_loss" not in captured[0]


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
        [{"signal": "v2", "min_unlock_pct": 0.02, "cohort": "team"}]
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
    sharpe: float,
    win_rate: float = 0.5,
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
