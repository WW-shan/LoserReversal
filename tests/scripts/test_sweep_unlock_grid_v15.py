from __future__ import annotations

import pandas as pd

from scripts import sweep_unlock_grid_v15 as sweep


def test_cli_smoke_writes_parquet_and_report(monkeypatch, tmp_path, capsys):
    out = tmp_path / "unlock_grid.parquet"
    report = tmp_path / "grid_report.md"

    monkeypatch.setattr(sweep, "read_unlocks", lambda path=None: _events(), raising=False)
    monkeypatch.setattr(sweep, "load_coverage", lambda path: _coverage(), raising=False)
    monkeypatch.setattr(sweep, "load_prices", lambda events, candles_dir: {"ARB": _prices()}, raising=False)
    monkeypatch.setattr(sweep, "run_main_grid", lambda *args, **kwargs: _grid_rows(60))
    monkeypatch.setattr(sweep, "run_vesting_sub_sweep", lambda *args, **kwargs: _vesting_rows())

    exit_code = sweep.main(
        [
            "--out",
            str(out),
            "--report",
            str(report),
            "--init-cash",
            "5000",
            "--fees",
            "0",
            "--slippage",
            "0",
        ]
    )

    assert exit_code == 0
    assert len(pd.read_parquet(out)) == 63
    assert "Top-5 by Sharpe" in report.read_text(encoding="utf-8")
    assert "Top-5 by Sharpe" in capsys.readouterr().out


def test_run_main_grid_returns_60_cells(monkeypatch):
    seen_cells = []

    def fake_run_cell(events, prices, coverage, cell, *, init_cash, fees, slippage):
        seen_cells.append(cell)
        return {
            "signal": cell.code,
            "min_unlock_pct": cell.min_unlock_pct,
            "cohort": cell.cohort_name,
            "n_trades": 31,
            "win_rate": 0.51,
            "sharpe": 1.0,
            "sortino": 1.2,
            "max_dd": -0.03,
            "total_return": 0.04,
            "mean_pnl": 1.5,
            "median_pnl": 1.0,
        }

    monkeypatch.setattr(sweep, "run_cell", fake_run_cell)

    rows = sweep.run_main_grid(
        _events(),
        {"ARB": _prices()},
        _coverage(),
        init_cash=10_000.0,
        fees=0.0,
        slippage=0.0,
    )

    assert len(rows) == 60
    assert len(seen_cells) == 60
    assert all(row["eligible"] for row in rows)
    assert rows[0]["signal"] == "v1"
    assert rows[-1]["signal"] == "v5"


def test_vesting_sub_sweep_runs_best_eligible_cell_for_each_type(monkeypatch):
    calls = []
    main_rows = [
        _row(signal="v1", min_unlock_pct=0.01, cohort="all", sharpe=0.5, n_trades=31),
        _row(signal="v3", min_unlock_pct=0.05, cohort="team", sharpe=2.0, n_trades=35),
        _row(signal="v5", min_unlock_pct=0.10, cohort="all", sharpe=3.0, n_trades=2),
    ]

    def fake_run_cell(events, prices, coverage, cell, *, init_cash, fees, slippage):
        calls.append((events["vesting_type"].unique().tolist(), cell))
        return _row(
            signal=cell.code,
            min_unlock_pct=cell.min_unlock_pct,
            cohort=cell.cohort_name,
            sharpe=float(len(calls)),
            n_trades=40,
        )

    monkeypatch.setattr(sweep, "run_cell", fake_run_cell)

    rows = sweep.run_vesting_sub_sweep(
        _vesting_events(),
        {"ARB": _prices()},
        _coverage(),
        main_rows,
        init_cash=10_000.0,
        fees=0.0,
        slippage=0.0,
    )

    assert [row["cohort"] for row in rows] == [
        "vesting:cliff",
        "vesting:step",
        "vesting:linear",
    ]
    assert [call[0] for call in calls] == [["cliff"], ["step"], ["linear"]]
    assert {call[1].code for call in calls} == {"v3"}
    assert {call[1].min_unlock_pct for call in calls} == {0.05}
    assert {call[1].cohort_name for call in calls} == {"team"}


def _prices() -> pd.Series:
    index = pd.date_range("2026-01-01", periods=10, freq="1D", tz="UTC")
    return pd.Series(range(10), index=index, name="close", dtype="float64")


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


def _grid_rows(count: int) -> list[dict]:
    return [_row(sharpe=float(count - index)) for index in range(count)]


def _vesting_rows() -> list[dict]:
    return [
        _row(cohort="vesting:cliff", sharpe=3.0),
        _row(cohort="vesting:step", sharpe=2.0),
        _row(cohort="vesting:linear", sharpe=1.0),
    ]


def _vesting_events() -> pd.DataFrame:
    rows = []
    for vesting_type in ("cliff", "step", "linear"):
        row = _events().iloc[0].to_dict()
        row["vesting_type"] = vesting_type
        rows.append(row)
    return pd.DataFrame(rows)


def _row(
    *,
    signal: str = "v1",
    min_unlock_pct: float = 0.01,
    cohort: str = "team",
    sharpe: float = 1.0,
    n_trades: int = 31,
) -> dict:
    return {
        "signal": signal,
        "min_unlock_pct": min_unlock_pct,
        "cohort": cohort,
        "n_trades": n_trades,
        "win_rate": 0.5,
        "sharpe": sharpe,
        "sortino": 1.0,
        "max_dd": -0.02,
        "total_return": 0.03,
        "mean_pnl": 1.0,
        "median_pnl": 1.0,
        "eligible": n_trades >= 30,
    }
