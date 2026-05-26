from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pandas as pd

from scripts import run_funding_extreme_backtest as backtest
from scripts import sweep_funding_extreme_grid as sweep


def test_sweep_produces_48_aggregate_rows(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(sweep, "run_single_config_with_coverage", _fake_with_coverage)

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
    monkeypatch.setattr(sweep, "run_single_config_with_coverage", _fake_with_coverage)

    sweep.run_grid_sweep(sweep.GridSweepConfig(out=out, report=report))

    frame = pd.read_parquet(out)
    assert {"BTC", "ETH", "AGGREGATE"}.issubset(set(frame["token"]))
    assert len(frame.loc[frame["token"] == "AGGREGATE"]) == 48
    assert report.exists()


def test_sweep_ranks_top_cell_by_aggregate_sharpe(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(sweep, "run_single_config_with_coverage", _fake_with_coverage)

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
    monkeypatch.setattr(sweep, "run_single_config_with_coverage", _fake_with_coverage)

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


def test_sweep_report_includes_coverage_section_with_skipped_tokens(
    monkeypatch, tmp_path: Path
):
    """Report Coverage section must list skipped tokens (data transparency)."""
    out = tmp_path / "funding_extreme_grid.parquet"
    report = tmp_path / "funding_extreme_grid.md"

    def fake_with_skips(config) -> backtest.SingleConfigResult:
        frame = _fake_single_config(config)
        return backtest.SingleConfigResult(frame=frame, skipped_tokens=["DOGE", "ADA"])

    monkeypatch.setattr(sweep, "run_single_config_with_coverage", fake_with_skips)

    sweep.run_grid_sweep(sweep.GridSweepConfig(out=out, report=report))

    text = report.read_text(encoding="utf-8")
    assert "## Coverage" in text
    assert "DOGE" in text
    assert "ADA" in text
    assert "Aggregate covers" in text


def test_sweep_cli_file_execution_smoke(tmp_path: Path):
    funding_dir = tmp_path / "funding"
    candles_dir = tmp_path / "candles"
    out = tmp_path / "funding_extreme_grid.parquet"
    report = tmp_path / "funding_extreme_grid.md"
    _write_cli_fixture(funding_dir, candles_dir)

    result = subprocess.run(
        [
            sys.executable,
            "scripts/sweep_funding_extreme_grid.py",
            "--funding-dir",
            str(funding_dir),
            "--candles-dir",
            str(candles_dir),
            "--out",
            str(out),
            "--report",
            str(report),
            "--taker-fee",
            "0",
            "--slippage",
            "0",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert out.exists()
    assert len(pd.read_parquet(out).loc[lambda frame: frame["token"].eq("AGGREGATE")]) == 48


def test_sweep_propagates_price_interval_to_backtest_config(monkeypatch, tmp_path: Path):
    """run_grid_sweep must forward sweep config price_interval into each BacktestConfig."""
    captured: list[str] = []

    def fake_with_capture(config) -> backtest.SingleConfigResult:
        captured.append(config.price_interval)
        return backtest.SingleConfigResult(
            frame=_fake_single_config(config),
            skipped_tokens=[],
        )

    monkeypatch.setattr(sweep, "run_single_config_with_coverage", fake_with_capture)

    sweep.run_grid_sweep(
        sweep.GridSweepConfig(
            out=tmp_path / "grid.parquet",
            report=tmp_path / "grid.md",
            price_interval="4h",
        )
    )

    assert captured  # at least one cell ran
    assert all(value == "4h" for value in captured)


def test_sweep_cli_accepts_price_interval_flag(monkeypatch, tmp_path: Path):
    """`--price-interval 4h` parses cleanly and is forwarded to GridSweepConfig."""
    captured_config: dict[str, sweep.GridSweepConfig] = {}

    def fake_run(config: sweep.GridSweepConfig) -> dict[str, object]:
        captured_config["config"] = config
        return {"frame": pd.DataFrame(), "ranking": pd.DataFrame()}

    monkeypatch.setattr(sweep, "run_grid_sweep", fake_run)

    exit_code = sweep.main(
        [
            "--funding-dir",
            str(tmp_path / "funding"),
            "--candles-dir",
            str(tmp_path / "candles"),
            "--out",
            str(tmp_path / "grid.parquet"),
            "--report",
            str(tmp_path / "grid.md"),
            "--taker-fee",
            "0",
            "--slippage",
            "0",
            "--price-interval",
            "4h",
        ]
    )

    assert exit_code == 0
    assert captured_config["config"].price_interval == "4h"


def test_sweep_report_coverage_section_mentions_interval(monkeypatch, tmp_path: Path):
    """Coverage section should declare which candle interval drove the run."""
    out = tmp_path / "grid.parquet"
    report = tmp_path / "grid.md"

    def fake_with_skips(config) -> backtest.SingleConfigResult:
        return backtest.SingleConfigResult(
            frame=_fake_single_config(config),
            skipped_tokens=["DOGE"],
        )

    monkeypatch.setattr(sweep, "run_single_config_with_coverage", fake_with_skips)

    sweep.run_grid_sweep(
        sweep.GridSweepConfig(out=out, report=report, price_interval="4h")
    )

    text = report.read_text(encoding="utf-8")
    assert "4h" in text
    assert "price_interval" in text or "price interval" in text.lower()


def test_sweep_default_price_interval_is_1h():
    """Default price interval stays 1h to preserve back-compat."""
    config = sweep.GridSweepConfig()
    assert config.price_interval == "1h"


def _fake_with_coverage(config) -> backtest.SingleConfigResult:
    return backtest.SingleConfigResult(
        frame=_fake_single_config(config),
        skipped_tokens=[],
    )


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


def _write_cli_fixture(funding_dir: Path, candles_dir: Path) -> None:
    funding_dir.mkdir(parents=True)
    candles_dir.mkdir(parents=True)
    hours = 24 * 102
    timestamps = pd.date_range("2025-01-01T00:00:00Z", periods=hours, freq="1h", tz="UTC")
    rates = [0.0001] * hours
    for position in range(24 * 92, 24 * 92 + 5):
        rates[position] = 0.0010

    for token in ("BTC", "ETH"):
        pd.DataFrame(
            {
                "timestamp": timestamps,
                "funding_rate": rates,
                "premium": [0.0] * hours,
            }
        ).to_parquet(funding_dir / f"{token}.parquet", index=False)

        close = pd.Series(100.0, index=timestamps) + pd.Series(range(hours), index=timestamps) * 0.01
        pd.DataFrame(
            {
                "timestamp": timestamps,
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 1.0,
            }
        ).to_parquet(candles_dir / f"{token}_1h.parquet", index=False)
