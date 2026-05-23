from __future__ import annotations

import pandas as pd
import pyarrow.parquet as pq

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


def test_date_filter_includes_date_end_boundary():
    events = _events()
    later = events.iloc[0].to_dict()
    later["unlock_date"] = pd.Timestamp("2026-01-06T00:00:00Z")
    events = pd.concat([events, pd.DataFrame([later])], ignore_index=True)

    result = sweep._filter_events_by_date(
        events,
        date_start=pd.Timestamp("2026-01-05T00:00:00Z"),
        date_end=pd.Timestamp("2026-01-05T00:00:00Z"),
    )

    assert result["unlock_date"].tolist() == [pd.Timestamp("2026-01-05T00:00:00Z")]


def test_load_prices_reads_only_available_1d_candles(tmp_path):
    candles_dir = tmp_path / "candles"
    candles_dir.mkdir()
    timestamps = pd.date_range("2026-01-01", periods=2, freq="1D", tz="UTC")
    pd.DataFrame({"timestamp": timestamps, "close": [100.0, 101.0]}).to_parquet(
        candles_dir / "ARB_1d.parquet",
        index=False,
    )
    events = pd.concat(
        [
            _events(),
            pd.DataFrame([{**_events().iloc[0].to_dict(), "token": "MISSING"}]),
        ],
        ignore_index=True,
    )

    prices = sweep.load_prices(events, candles_dir)

    assert set(prices) == {"ARB"}
    assert prices["ARB"].index.tz is not None
    assert prices["ARB"].tolist() == [100.0, 101.0]


def test_best_main_row_ignores_ineligible_higher_sharpe():
    rows = [
        _row(signal="v1", sharpe=10.0, n_trades=2),
        _row(signal="v2", sharpe=1.5, n_trades=30),
    ]

    assert sweep._best_main_row(rows)["signal"] == "v2"


def test_vesting_sub_sweep_falls_back_to_best_sharpe_when_no_eligible_rows(monkeypatch):
    seen_codes = []
    rows = [
        _row(signal="v1", sharpe=1.0, n_trades=2),
        _row(signal="v4", sharpe=2.0, n_trades=3),
    ]

    def fake_run_cell(events, prices, coverage, cell, *, init_cash, fees, slippage):
        seen_codes.append(cell.code)
        return _row(signal=cell.code, n_trades=3)

    monkeypatch.setattr(sweep, "run_cell", fake_run_cell)

    result = sweep.run_vesting_sub_sweep(
        _vesting_events(),
        {"ARB": _prices()},
        _coverage(),
        rows,
        init_cash=10_000.0,
        fees=0.0,
        slippage=0.0,
    )

    assert [row["cohort"] for row in result] == [
        "vesting:cliff",
        "vesting:step",
        "vesting:linear",
    ]
    assert seen_codes == ["v4", "v4", "v4"]


def test_top5_table_lists_only_eligible_rows():
    rows = [
        _row(signal="v1", sharpe=9.0, n_trades=2),
        _row(signal="v2", sharpe=2.0, n_trades=30),
    ]

    table = sweep._top5_table(rows)

    assert "| 1 | v2 |" in table
    assert "v1" not in table


def test_render_report_includes_vesting_subsection(tmp_path):
    report = tmp_path / "grid_report.md"
    rows = [
        _row(signal="v1", min_unlock_pct=0.02, cohort="team", sharpe=1.6, n_trades=47),
        *_vesting_rows(),
    ]

    sweep._write_report(report, rows, sweep.GridSweepConfig(report=report))

    text = report.read_text(encoding="utf-8")
    assert "## Vesting Sub-Sweep" in text
    assert "| vesting_type | n_trades | win_rate | sharpe | max_dd | total_return |" in text
    assert "| cliff |" in text
    assert "| step |" in text
    assert "| linear |" in text


def test_report_includes_methodology_section(tmp_path):
    report = tmp_path / "grid_report.md"

    sweep._write_report(report, _grid_rows(2), sweep.GridSweepConfig(report=report))

    text = report.read_text(encoding="utf-8")
    assert "## Methodology" in text
    assert "active-capital" in text
    assert "Each token's signal is backtested independently" in text
    assert "Inactive tokens contribute zero" in text
    assert "Total return is relative to summed initial capital" in text


def test_parquet_has_methodology_metadata(monkeypatch, tmp_path):
    out = tmp_path / "unlock_grid.parquet"
    report = tmp_path / "grid_report.md"

    monkeypatch.setattr(sweep, "read_unlocks", lambda path=None: _events(), raising=False)
    monkeypatch.setattr(sweep, "load_coverage", lambda path: _coverage(), raising=False)
    monkeypatch.setattr(sweep, "load_prices", lambda events, candles_dir: {"ARB": _prices()}, raising=False)
    monkeypatch.setattr(sweep, "run_main_grid", lambda *args, **kwargs: _grid_rows(60))
    monkeypatch.setattr(sweep, "run_vesting_sub_sweep", lambda *args, **kwargs: _vesting_rows())

    sweep.run_sweep(sweep.GridSweepConfig(out=out, report=report, init_cash=12_345.0))

    metadata = pq.read_metadata(out).metadata or {}
    assert b"methodology" in metadata
    assert b"active-capital" in metadata[b"methodology"]
    assert metadata[b"cell_budget_per_token"] == b"12345.00"


def test_date_range_clips_price_window_not_just_events(monkeypatch, tmp_path):
    out = tmp_path / "unlock_grid.parquet"
    report = tmp_path / "grid_report.md"
    captured_prices: dict[str, pd.Series] = {}

    events = _events()
    events.loc[0, "unlock_date"] = pd.Timestamp("2025-01-02T00:00:00Z")
    price_index = pd.date_range("2024-12-30", periods=7, freq="1D", tz="UTC")
    prices = pd.Series(range(7), index=price_index, name="close", dtype="float64")

    def fake_run_main_grid(events_arg, prices_arg, *args, **kwargs):
        captured_prices["ARB"] = prices_arg["ARB"]
        return _grid_rows(1)

    monkeypatch.setattr(sweep, "read_unlocks", lambda path=None: events, raising=False)
    monkeypatch.setattr(sweep, "load_coverage", lambda path: _coverage(), raising=False)
    monkeypatch.setattr(sweep, "load_prices", lambda events_arg, candles_dir: {"ARB": prices})
    monkeypatch.setattr(sweep, "run_main_grid", fake_run_main_grid)
    monkeypatch.setattr(sweep, "run_vesting_sub_sweep", lambda *args, **kwargs: [])

    sweep.run_sweep(
        sweep.GridSweepConfig(
            out=out,
            report=report,
            date_start=pd.Timestamp("2025-01-01T00:00:00Z"),
            date_end=pd.Timestamp("2025-01-03T00:00:00Z"),
        )
    )

    assert captured_prices["ARB"].index.tolist() == [
        pd.Timestamp("2025-01-01T00:00:00Z"),
        pd.Timestamp("2025-01-02T00:00:00Z"),
        pd.Timestamp("2025-01-03T00:00:00Z"),
    ]


def test_parquet_has_sweep_kind_column(monkeypatch, tmp_path):
    out = tmp_path / "unlock_grid.parquet"
    report = tmp_path / "grid_report.md"

    def fake_run_cell(events, prices, coverage, cell, *, init_cash, fees, slippage):
        return _row(
            signal=cell.code,
            min_unlock_pct=cell.min_unlock_pct,
            cohort=cell.cohort_name,
            n_trades=31,
        )

    monkeypatch.setattr(sweep, "read_unlocks", lambda path=None: _vesting_events(), raising=False)
    monkeypatch.setattr(sweep, "load_coverage", lambda path: _coverage(), raising=False)
    monkeypatch.setattr(sweep, "load_prices", lambda events_arg, candles_dir: {"ARB": _prices()})
    monkeypatch.setattr(sweep, "run_cell", fake_run_cell)

    sweep.run_sweep(sweep.GridSweepConfig(out=out, report=report))

    frame = pd.read_parquet(out)
    assert "sweep_kind" in frame.columns
    assert frame["sweep_kind"].value_counts().to_dict() == {"category": 60, "vesting": 3}


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
