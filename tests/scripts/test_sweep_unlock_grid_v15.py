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
    assert len(pd.read_parquet(out)) == 60
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
    return [
        {
            "signal": "v1",
            "min_unlock_pct": 0.01,
            "cohort": "team",
            "n_trades": 31,
            "win_rate": 0.5,
            "sharpe": float(count - index),
            "sortino": 1.0,
            "max_dd": -0.02,
            "total_return": 0.03,
            "mean_pnl": 1.0,
            "median_pnl": 1.0,
            "eligible": True,
        }
        for index in range(count)
    ]
