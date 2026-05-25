"""Tests for Phase 1.5 Ablation A bootstrap CI script."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from scripts import bootstrap_phase1_5 as bootstrap


TRADE_SCHEMA = pa.schema(
    [
        ("signal", pa.string()),
        ("split_idx", pa.int64()),
        ("token", pa.string()),
        ("entry_ts", pa.timestamp("us", tz="UTC")),
        ("exit_ts", pa.timestamp("us", tz="UTC")),
        ("direction", pa.int64()),
        ("return", pa.float64()),
        ("hold_days", pa.float64()),
        ("win", pa.bool_()),
    ]
)


def test_positive_sharpe_returns_have_lower_bound_above_zero(tmp_path: Path) -> None:
    rng = np.random.default_rng(seed=11)
    returns = rng.normal(loc=0.08, scale=0.05, size=60)
    parquet = _write_trades(tmp_path, returns=returns)

    result = bootstrap.run_bootstrap(
        bootstrap.BootstrapConfig(
            input=parquet,
            signal="v2",
            phase="OOS",
            iterations=4000,
            seed=11,
            trades_per_year=14.4,
            report=tmp_path / "report.md",
        )
    )

    assert result["lower_2_5"] > 0.0
    assert result["upper_97_5"] > result["lower_2_5"]
    assert result["median_50"] > 0.0
    assert result["decision"] == "robust"


def test_negative_sharpe_returns_have_upper_bound_below_zero(tmp_path: Path) -> None:
    rng = np.random.default_rng(seed=23)
    returns = rng.normal(loc=-0.08, scale=0.05, size=60)
    parquet = _write_trades(tmp_path, returns=returns)

    result = bootstrap.run_bootstrap(
        bootstrap.BootstrapConfig(
            input=parquet,
            signal="v2",
            phase="OOS",
            iterations=4000,
            seed=23,
            trades_per_year=14.4,
            report=tmp_path / "report.md",
        )
    )

    assert result["upper_97_5"] < 0.0
    assert result["median_50"] < 0.0
    assert result["decision"] == "lucky-fold"


def test_borderline_returns_have_ci_spanning_zero(tmp_path: Path) -> None:
    rng = np.random.default_rng(seed=42)
    returns = rng.normal(loc=0.001, scale=0.20, size=36)
    parquet = _write_trades(tmp_path, returns=returns)

    result = bootstrap.run_bootstrap(
        bootstrap.BootstrapConfig(
            input=parquet,
            signal="v2",
            phase="OOS",
            iterations=4000,
            seed=42,
            trades_per_year=14.4,
            report=tmp_path / "report.md",
        )
    )

    assert result["lower_2_5"] < 0.0 < result["upper_97_5"]
    assert result["decision"] == "inconclusive"


def test_filters_signal_before_resampling(tmp_path: Path) -> None:
    rng = np.random.default_rng(seed=5)
    v2_returns = rng.normal(loc=0.10, scale=0.05, size=20).tolist()
    v1_returns = rng.normal(loc=-0.50, scale=0.05, size=20).tolist()
    parquet = _write_mixed_trades(tmp_path, v2_returns=v2_returns, v1_returns=v1_returns)

    result = bootstrap.run_bootstrap(
        bootstrap.BootstrapConfig(
            input=parquet,
            signal="v2",
            phase="OOS",
            iterations=2000,
            seed=5,
            trades_per_year=14.4,
            report=tmp_path / "report.md",
        )
    )

    assert result["n_trades"] == 20
    assert result["decision"] == "robust"


def test_empty_input_raises_runtime_error(tmp_path: Path) -> None:
    parquet = _write_trades(tmp_path, returns=np.array([], dtype="float64"))

    with pytest.raises(RuntimeError, match="no trades"):
        bootstrap.run_bootstrap(
            bootstrap.BootstrapConfig(
                input=parquet,
                signal="v2",
                phase="OOS",
                iterations=1000,
                seed=0,
                trades_per_year=14.4,
                report=tmp_path / "report.md",
            )
        )


def test_cli_smoke_writes_report_and_returns_zero(tmp_path: Path, capsys) -> None:
    rng = np.random.default_rng(seed=7)
    returns = rng.normal(loc=0.05, scale=0.10, size=36)
    parquet = _write_trades(tmp_path, returns=returns)
    report = tmp_path / "phase-1-5-bootstrap-ci.md"

    exit_code = bootstrap.main(
        [
            "--input",
            str(parquet),
            "--signal",
            "v2",
            "--phase",
            "OOS",
            "--iterations",
            "2000",
            "--seed",
            "7",
            "--trades-per-year",
            "14.4",
            "--report",
            str(report),
        ]
    )

    assert exit_code == 0
    assert report.exists()
    text = report.read_text(encoding="utf-8")
    assert "Bootstrap CI" in text
    assert "2.5%" in text
    assert "97.5%" in text
    captured = capsys.readouterr()
    assert "wrote report" in captured.out


def _write_trades(tmp_path: Path, *, returns: np.ndarray) -> Path:
    frame = pd.DataFrame(
        {
            "signal": pd.array(["v2"] * len(returns), dtype="string"),
            "split_idx": pd.array([0] * len(returns), dtype="int64"),
            "token": pd.array(["TEST"] * len(returns), dtype="string"),
            "entry_ts": pd.to_datetime(
                pd.date_range("2024-01-01", periods=len(returns), freq="7D", tz="UTC")
            ),
            "exit_ts": pd.to_datetime(
                pd.date_range("2024-02-01", periods=len(returns), freq="7D", tz="UTC")
            ),
            "direction": pd.array([-1] * len(returns), dtype="int64"),
            "return": pd.array(list(returns), dtype="float64"),
            "hold_days": pd.array([30.0] * len(returns), dtype="float64"),
            "win": pd.array([float(value) > 0 for value in returns], dtype="bool"),
        }
    )
    path = tmp_path / "trades.parquet"
    table = pa.Table.from_pandas(frame, schema=TRADE_SCHEMA, preserve_index=False)
    pq.write_table(table, path, coerce_timestamps="us")
    return path


def _write_mixed_trades(
    tmp_path: Path,
    *,
    v2_returns: list[float],
    v1_returns: list[float],
) -> Path:
    rows: list[dict[str, object]] = []
    for offset, value in enumerate(v2_returns):
        rows.append(_trade_row("v2", offset, value))
    for offset, value in enumerate(v1_returns):
        rows.append(_trade_row("v1", offset + len(v2_returns), value))
    frame = pd.DataFrame(rows)
    frame = frame.astype(
        {
            "signal": "string",
            "split_idx": "int64",
            "token": "string",
            "direction": "int64",
            "return": "float64",
            "hold_days": "float64",
            "win": "bool",
        }
    )
    path = tmp_path / "trades_mixed.parquet"
    table = pa.Table.from_pandas(frame, schema=TRADE_SCHEMA, preserve_index=False)
    pq.write_table(table, path, coerce_timestamps="us")
    return path


def _trade_row(signal: str, offset: int, value: float) -> dict[str, object]:
    entry = pd.Timestamp("2024-01-01", tz="UTC") + pd.Timedelta(days=7 * offset)
    return {
        "signal": signal,
        "split_idx": 0,
        "token": "TEST",
        "entry_ts": entry,
        "exit_ts": entry + pd.Timedelta(days=30),
        "direction": -1,
        "return": float(value),
        "hold_days": 30.0,
        "win": float(value) > 0,
    }
