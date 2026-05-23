from __future__ import annotations

import pandas as pd

from signals.unlock_grid import GridCell
from signals.unlock_walkforward import compose_portfolio
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

    cell = select_best_config(
        grid_df,
        "v1",
        _events(),
        {"ARB": _prices()},
        _coverage(),
        min_n_trades=15,
    )

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
            "n_trades": 4,
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


def test_select_best_config_default_threshold_accepts_five_trades(monkeypatch):
    grid_df = pd.DataFrame(
        [
            {"signal": "v1", "min_unlock_pct": 0.01, "cohort": "team"},
            {"signal": "v1", "min_unlock_pct": 0.02, "cohort": "team"},
        ]
    )
    stats = {
        (0.01, "team"): {"n_trades": 4, "sharpe": 9.0},
        (0.02, "team"): {"n_trades": 5, "sharpe": 1.0},
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
    assert cell.min_unlock_pct == 0.02


def test_run_per_signal_walkforward_uses_default_threshold_five(monkeypatch):
    splits = [_split("2026-01-01", "2026-02-01", "2026-02-01", "2026-03-01")]
    captured_min_n_trades: list[int] = []

    def fake_select_best_config(
        grid_df,
        signal_code,
        train_events,
        train_prices,
        train_coverage,
        min_n_trades=15,
        **kwargs,
    ):
        captured_min_n_trades.append(min_n_trades)
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
        ["v1"],
        grid_df=_grid_df(),
    )

    assert captured_min_n_trades == [5]


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


def test_run_per_signal_walkforward_falls_back_to_best_positive_trade(monkeypatch):
    splits = [_split("2026-01-01", "2026-02-01", "2026-02-01", "2026-03-01")]
    grid_df = pd.DataFrame(
        [
            {"signal": "v1", "min_unlock_pct": 0.01, "cohort": "team"},
            {"signal": "v1", "min_unlock_pct": 0.02, "cohort": "team"},
        ]
    )
    events = pd.concat(
        [
            _events(),
            _events().assign(unlock_date=pd.Timestamp("2026-02-05T00:00:00Z")),
        ],
        ignore_index=True,
    )

    monkeypatch.setattr(
        "signals.unlock_walkforward.select_best_config",
        lambda *args, **kwargs: None,
    )

    def fake_run_cell(events_arg, prices, coverage, cell, *, init_cash, fees, slippage):
        if events_arg["unlock_date"].max() < pd.Timestamp("2026-02-01T00:00:00Z"):
            sharpe = 1.5 if cell.min_unlock_pct == 0.02 else 0.5
            return _stats(cell, n_trades=1, sharpe=sharpe)
        assert cell.min_unlock_pct == 0.02
        return _stats(cell, n_trades=2, sharpe=0.8)

    monkeypatch.setattr("signals.unlock_walkforward.run_cell", fake_run_cell)

    result = run_per_signal_walkforward(
        events,
        {"ARB": _prices()},
        _coverage(),
        splits,
        ["v1"],
        grid_df=grid_df,
    )

    split_row = result.loc[result["split_idx"].eq(0)].iloc[0]
    assert split_row["selected_min_pct"] == 0.02
    assert split_row["n_trades"] == 2


def test_run_per_signal_walkforward_marks_no_train_signal_when_fallback_has_no_trades(
    monkeypatch,
):
    splits = [_split("2026-01-01", "2026-02-01", "2026-02-01", "2026-03-01")]
    grid_df = pd.DataFrame(
        [
            {"signal": "v1", "min_unlock_pct": 0.01, "cohort": "team"},
            {"signal": "v1", "min_unlock_pct": 0.02, "cohort": "team"},
        ]
    )

    monkeypatch.setattr(
        "signals.unlock_walkforward.select_best_config",
        lambda *args, **kwargs: None,
    )

    def fake_run_cell(events, prices, coverage, cell, *, init_cash, fees, slippage):
        if events["unlock_date"].max() < pd.Timestamp("2026-02-01T00:00:00Z"):
            return _stats(cell, n_trades=0, sharpe=0.0)
        return _stats(cell, n_trades=2, sharpe=3.0)

    monkeypatch.setattr("signals.unlock_walkforward.run_cell", fake_run_cell)

    result = run_per_signal_walkforward(
        _events(),
        {"ARB": _prices()},
        _coverage(),
        splits,
        ["v1"],
        grid_df=grid_df,
    )

    split_row = result.loc[result["split_idx"].eq(0)].iloc[0]
    assert pd.isna(split_row["selected_min_pct"])
    assert split_row["selected_cohort"] == "no_train_signal"
    assert split_row["n_trades"] == 0
    assert split_row["sharpe"] == 0.0


def test_compose_portfolio_equal_weights_K2(monkeypatch):
    splits = [_split("2026-01-01", "2026-02-01", "2026-02-01", "2026-03-01")]
    per_signal_df = pd.DataFrame(
        [
            _per_signal_row("v1", 0, 0.02, "team", sharpe=0.5),
            _per_signal_row("v2", 0, 0.01, "team+investor", sharpe=0.4),
            _per_signal_row("v3", 0, 0.10, "all", sharpe=-0.1),
            _per_signal_aggregate("v1", sharpe=1.4),
            _per_signal_aggregate("v2", sharpe=1.1),
            _per_signal_aggregate("v3", sharpe=0.2),
        ]
    )
    stats = {
        "v1": {"n_trades": 5, "win_rate": 0.40, "sharpe": 1.0, "max_dd": -0.02},
        "v2": {"n_trades": 5, "win_rate": 0.80, "sharpe": 3.0, "max_dd": -0.06},
    }

    def fake_run_cell(events, prices, coverage, cell, *, init_cash, fees, slippage):
        row = stats[cell.code]
        return _stats(
            cell,
            n_trades=row["n_trades"],
            win_rate=row["win_rate"],
            sharpe=row["sharpe"],
            max_dd=row["max_dd"],
        )

    monkeypatch.setattr("signals.unlock_walkforward.run_cell", fake_run_cell)

    result = compose_portfolio(
        per_signal_df,
        _events(),
        {"ARB": _prices()},
        _coverage(),
        splits,
        top_k=2,
    )

    split_row = result.loc[result["split_idx"].eq(0)].iloc[0]
    assert split_row["signal"] == "top_2_equal_weight"
    assert split_row["selected_cohort"] == "v1:team;v2:team+investor"
    assert split_row["n_trades"] == 10
    assert split_row["sharpe"] == 2.0
    assert split_row["win_rate"] == 0.6
    assert split_row["max_dd"] == -0.04


def test_compose_portfolio_labels_actual_selected_components(monkeypatch):
    splits = [_split("2026-01-01", "2026-02-01", "2026-02-01", "2026-03-01")]
    per_signal_df = pd.DataFrame(
        [
            _per_signal_row("v1", 0, 0.02, "team", sharpe=1.0),
            _per_signal_row("v2", 0, float("nan"), "no_train_signal", sharpe=0.2),
            _per_signal_aggregate("v1", sharpe=1.0),
            _per_signal_aggregate("v2", sharpe=0.2),
        ]
    )

    monkeypatch.setattr(
        "signals.unlock_walkforward.run_cell",
        lambda events, prices, coverage, cell, **kwargs: _stats(
            cell,
            n_trades=4,
            sharpe=1.5,
        ),
    )

    result = compose_portfolio(
        per_signal_df,
        _events(),
        {"ARB": _prices()},
        _coverage(),
        splits,
        top_k=2,
    )

    split_row = result.loc[result["split_idx"].eq(0)].iloc[0]
    assert split_row["signal"] == "top_1_equal_weight"
    assert split_row["selected_cohort"] == "v1:team"
    assert split_row["n_trades"] == 4


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


def _per_signal_row(
    signal: str,
    split_idx: int,
    min_unlock_pct: float,
    cohort: str,
    *,
    sharpe: float,
) -> dict:
    split = _split("2026-01-01", "2026-02-01", "2026-02-01", "2026-03-01")
    return {
        "kind": "per_signal",
        "signal": signal,
        "split_idx": split_idx,
        "train_start": split[0][0],
        "train_end": split[0][1],
        "test_start": split[1][0],
        "test_end": split[1][1],
        "selected_min_pct": min_unlock_pct,
        "selected_cohort": cohort,
        "n_trades": 3,
        "sharpe": sharpe,
        "sortino": sharpe + 0.5,
        "win_rate": 0.5,
        "max_dd": -0.02,
        "total_return": 0.03,
        "fallback_used": False,
    }


def _per_signal_aggregate(signal: str, *, sharpe: float) -> dict:
    row = _per_signal_row(signal, -1, float("nan"), "aggregate", sharpe=sharpe)
    row["train_start"] = pd.NaT
    row["train_end"] = pd.NaT
    row["test_start"] = pd.NaT
    row["test_end"] = pd.NaT
    return row
