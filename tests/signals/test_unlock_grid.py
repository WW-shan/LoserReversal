from __future__ import annotations

import pandas as pd

from signals.unlock_grid import (
    CATEGORY_COHORTS,
    GridCell,
    SIGNAL_REGISTRY,
    SIZE_THRESHOLDS,
    apply_category_filter,
    iter_grid,
    run_cell,
)


def _events() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"token": "ARB", "category": "insiders"},
            {"token": "APT", "category": "privateSale"},
            {"token": "OP", "category": "ecosystem"},
        ]
    )


def test_signal_registry_has_all_5_versions():
    assert set(SIGNAL_REGISTRY) == {"v1", "v2", "v3", "v4", "v5"}
    assert SIGNAL_REGISTRY["v1"].direction == "short"
    assert SIGNAL_REGISTRY["v5"].direction == "long"


def test_category_cohort_team_only_keeps_insiders():
    result = apply_category_filter(_events(), CATEGORY_COHORTS["team"])

    assert result["token"].tolist() == ["ARB"]


def test_category_cohort_team_investor_keeps_insiders_and_private_sale():
    result = apply_category_filter(_events(), CATEGORY_COHORTS["team+investor"])

    assert result["token"].tolist() == ["ARB", "APT"]


def test_category_cohort_all_passes_everything():
    result = apply_category_filter(_events(), CATEGORY_COHORTS["all"])

    assert result["token"].tolist() == ["ARB", "APT", "OP"]


def test_iter_grid_yields_60_cells():
    cells = list(iter_grid())

    assert len(cells) == 5 * 4 * 3
    assert {cell.code for cell in cells} == set(SIGNAL_REGISTRY)
    assert {cell.min_unlock_pct for cell in cells} == set(SIZE_THRESHOLDS)
    assert {cell.cohort_name for cell in cells} == set(CATEGORY_COHORTS)


def test_run_cell_returns_stats_keys(monkeypatch):
    prices = {"ARB": _prices()}
    events = _grid_events([{"token": "ARB", "unlock_date": "2026-01-05"}])
    coverage = _coverage([{"token": "ARB", "unlock_date": "2026-01-05", "coverage_status": "ok"}])
    cell = GridCell(
        code="v1",
        min_unlock_pct=0.02,
        cohort_name="team",
        signal_fn=_fake_signal,
        direction="short",
        category_filter={"insiders"},
    )

    monkeypatch.setattr("signals.unlock_grid.run_backtest", _fake_backtest)

    result = run_cell(
        events,
        prices,
        coverage,
        cell,
        init_cash=10_000.0,
        fees=0.0,
        slippage=0.0,
    )

    assert set(result) == {
        "signal",
        "min_unlock_pct",
        "cohort",
        "n_trades",
        "win_rate",
        "sharpe",
        "sortino",
        "max_dd",
        "total_return",
        "mean_pnl",
        "median_pnl",
    }
    assert result["signal"] == "v1"
    assert result["n_trades"] == 1
    assert result["mean_pnl"] == 12.5


def test_run_cell_marks_long_direction_for_v5(monkeypatch):
    prices = {"ARB": _prices()}
    events = _grid_events([{"token": "ARB", "unlock_date": "2026-01-05"}])
    coverage = _coverage([{"token": "ARB", "unlock_date": "2026-01-05", "coverage_status": "ok"}])
    captured_directions: list[str] = []
    cell = GridCell(
        code="v5",
        min_unlock_pct=0.02,
        cohort_name="team",
        signal_fn=_fake_signal,
        direction="long",
        category_filter={"insiders"},
    )

    def fake_backtest(prices_arg, entries, exits, config):
        captured_directions.append(config.direction)
        return _fake_backtest(prices_arg, entries, exits, config)

    monkeypatch.setattr("signals.unlock_grid.run_backtest", fake_backtest)

    run_cell(
        events,
        prices,
        coverage,
        cell,
        init_cash=10_000.0,
        fees=0.0,
        slippage=0.0,
    )

    assert captured_directions == ["longonly"]


def _prices() -> pd.Series:
    index = pd.date_range("2026-01-01", periods=10, freq="1D", tz="UTC")
    return pd.Series([100.0 + index for index in range(10)], index=index, name="close")


def _grid_events(rows: list[dict]) -> pd.DataFrame:
    defaults = {
        "coingecko_id": "arb",
        "unlock_pct": 0.05,
        "category": "insiders",
        "has_hl_perp": True,
        "vesting_type": "cliff",
    }
    return pd.DataFrame([{**defaults, **row} for row in rows])


def _coverage(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _fake_signal(events, prices, min_unlock_pct, coverage):
    assert min_unlock_pct == 0.02
    assert coverage is not None
    assert events["category"].tolist() == ["insiders"]
    index = prices["ARB"].index
    entries = pd.Series(False, index=index, dtype=bool)
    exits = pd.Series(False, index=index, dtype=bool)
    entries.iloc[0] = True
    exits.iloc[-1] = True
    return {"ARB": (entries, exits)}


def _fake_backtest(prices_arg, entries, exits, config):
    class FakeTrades:
        records_readable = pd.DataFrame({"PnL": [12.5]})

        @staticmethod
        def count() -> int:
            return 1

        @staticmethod
        def win_rate() -> float:
            return 1.0

    class FakePortfolio:
        trades = FakeTrades()

    equity = pd.Series([10_000.0, 10_125.0], index=prices_arg.index[:2], name="equity")
    return type(
        "FakeBacktestResult",
        (),
        {
            "portfolio": FakePortfolio(),
            "stats": {
                "n_trades": 1,
                "win_rate": 1.0,
                "sharpe": 1.5,
                "sortino": 2.0,
                "max_dd": -0.01,
                "total_return": 0.0125,
            },
            "equity": equity,
        },
    )()
