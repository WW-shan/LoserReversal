from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts import sweep_funding_extreme_grid as sweep


def test_sweep_produces_48_aggregate_rows(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(sweep, "run_single_config", _fake_single_config)

    result = sweep.run_grid_sweep(
        sweep.GridSweepConfig(
            out=tmp_path / "funding_extreme_grid.parquet",
            report=tmp_path / "funding_extreme_grid.md",
        )
    )

    frame = result["frame"]
    assert len(frame.loc[frame["token"] == "AGGREGATE"]) == 48


def test_sweep_grid_param_dimensions():
    cells = list(sweep.iter_grid())

    assert len(cells) == 48
    assert {cell.z_threshold for cell in cells} == {1.5, 2.0, 2.5, 3.0}
    assert {cell.hold_hours for cell in cells} == {8, 24, 72, 168}
    assert {cell.lookback_days for cell in cells} == {14, 30, 90}
    assert len({(cell.z_threshold, cell.hold_hours, cell.lookback_days) for cell in cells}) == 48


def test_sweep_writes_parquet_with_token_and_aggregate_rows(monkeypatch, tmp_path: Path):
    out = tmp_path / "funding_extreme_grid.parquet"
    report = tmp_path / "funding_extreme_grid.md"
    monkeypatch.setattr(sweep, "run_single_config", _fake_single_config)

    sweep.run_grid_sweep(sweep.GridSweepConfig(out=out, report=report))

    frame = pd.read_parquet(out)
    assert {"BTC", "ETH", "AGGREGATE"}.issubset(set(frame["token"]))
    assert len(frame.loc[frame["token"] == "AGGREGATE"]) == 48
    assert report.exists()


def test_sweep_ranks_top_cell_by_aggregate_sharpe(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(sweep, "run_single_config", _fake_single_config)

    result = sweep.run_grid_sweep(
        sweep.GridSweepConfig(
            out=tmp_path / "funding_extreme_grid.parquet",
            report=tmp_path / "funding_extreme_grid.md",
        )
    )
    ranking = sweep.rank_aggregate_cells(result["frame"])

    top = ranking.iloc[0]
    assert top["z_threshold"] == 2.5
    assert top["hold_hours"] == 72
    assert top["lookback_days"] == 30
    assert top["sharpe"] == 9.0


def test_sweep_cli_smoke(monkeypatch, tmp_path: Path, capsys):
    out = tmp_path / "funding_extreme_grid.parquet"
    report = tmp_path / "funding_extreme_grid.md"
    monkeypatch.setattr(sweep, "run_single_config", _fake_single_config)

    exit_code = sweep.main(
        [
            "--funding-dir",
            str(tmp_path / "funding"),
            "--candles-dir",
            str(tmp_path / "candles"),
            "--out",
            str(out),
            "--report",
            str(report),
            "--taker-fee",
            "0",
            "--slippage",
            "0",
        ]
    )

    assert exit_code == 0
    assert out.exists()
    assert "Top-10 by Aggregate Sharpe" in report.read_text(encoding="utf-8")
    assert "wrote parquet" in capsys.readouterr().out


def _fake_single_config(config) -> pd.DataFrame:
    sharpe = _score(config.z_threshold, config.hold_hours, config.lookback_days)
    return pd.DataFrame(
        [
            _row(config, token="BTC", sharpe=sharpe - 0.1, n_trades=3),
            _row(config, token="ETH", sharpe=sharpe - 0.2, n_trades=4),
            _row(config, token="AGGREGATE", sharpe=sharpe, n_trades=7),
        ]
    )


def _score(z_threshold: float, hold_hours: int, lookback_days: int) -> float:
    if z_threshold == 2.5 and hold_hours == 72 and lookback_days == 30:
        return 9.0
    return float(z_threshold + hold_hours / 1000.0 + lookback_days / 10_000.0)


def _row(config, *, token: str, sharpe: float, n_trades: int) -> dict[str, float | int | str]:
    return {
        "token": token,
        "z_threshold": config.z_threshold,
        "hold_hours": config.hold_hours,
        "lookback_days": config.lookback_days,
        "n_trades": n_trades,
        "n_long": 0,
        "n_short": n_trades,
        "sharpe": sharpe,
        "annualized_return": sharpe / 10.0,
        "max_dd": -0.01,
        "win_rate": 0.5,
        "avg_trade_return": 0.01,
        "avg_hold_hours": float(config.hold_hours),
        "total_funding_paid": -0.001,
    }
