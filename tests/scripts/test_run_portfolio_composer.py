from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from scripts import run_portfolio_composer as runner


def test_cli_smoke_risk_parity_single_signal_writes_artifacts(tmp_path: Path) -> None:
    config = _write_config(tmp_path / "unlock_v1_stop.json", name="v1+D", signal="v1")
    out = tmp_path / "portfolio_composition.parquet"
    report = tmp_path / "portfolio_composition.md"

    exit_code = runner.main(
        [
            "--signals",
            str(tmp_path / "*.json"),
            "--method",
            "risk_parity",
            "--target-vol",
            "1.0",
            "--out",
            str(out),
            "--report",
            str(report),
        ]
    )

    assert exit_code == 0
    frame = pd.read_parquet(out)
    assert frame.shape[0] == 1
    assert frame.loc[0, "signal"] == "v1+D"
    assert frame.loc[0, "weight"] == 0.10
    assert report.exists()
    text = report.read_text(encoding="utf-8")
    assert "Correlation Matrix" in text
    assert "Risk Checks" in text


def test_cli_smoke_mean_variance_prioritizes_higher_return_signal(tmp_path: Path) -> None:
    _write_config(
        tmp_path / "a.json",
        name="a",
        signal="a",
        source_returns=[0.01, 0.00, 0.02, 0.01],
    )
    _write_config(
        tmp_path / "b.json",
        name="b",
        signal="b",
        source_returns=[0.05, 0.04, 0.06, 0.05],
    )
    out = tmp_path / "portfolio_composition.parquet"
    report = tmp_path / "portfolio_composition.md"

    exit_code = runner.main(
        [
            "--signals",
            str(tmp_path / "*.json"),
            "--method",
            "mean_variance",
            "--target-vol",
            "1.0",
            "--out",
            str(out),
            "--report",
            str(report),
        ]
    )

    assert exit_code == 0
    frame = pd.read_parquet(out).set_index("signal")
    assert frame.loc["b", "weight"] > frame.loc["a", "weight"]
    assert "Combined Stats" in report.read_text(encoding="utf-8")


def test_cli_smoke_equal_weight_uses_even_split(tmp_path: Path) -> None:
    _write_config(
        tmp_path / "a.json",
        name="a",
        signal="a",
        source_returns=[0.02, -0.01, 0.03, -0.02],
    )
    _write_config(
        tmp_path / "b.json",
        name="b",
        signal="b",
        source_returns=[-0.02, 0.01, -0.03, 0.02],
    )
    out = tmp_path / "portfolio_composition.parquet"
    report = tmp_path / "portfolio_composition.md"

    exit_code = runner.main(
        [
            "--signals",
            str(tmp_path / "*.json"),
            "--method",
            "equal_weight",
            "--target-vol",
            "1.0",
            "--out",
            str(out),
            "--report",
            str(report),
        ]
    )

    assert exit_code == 0
    frame = pd.read_parquet(out)
    assert frame["weight"].tolist() == [0.5, 0.5]
    assert "Kelly Sizing" in report.read_text(encoding="utf-8")


def _write_config(
    path: Path,
    *,
    name: str,
    signal: str,
    source_returns: list[float] | None = None,
) -> Path:
    source = path.with_suffix(".parquet")
    if source_returns is None:
        source_returns = [0.10, 0.04]
    pd.DataFrame(
        {
            "signal": [signal] * len(source_returns),
            "entry_ts": pd.date_range("2026-01-01", periods=len(source_returns), tz="UTC"),
            "return": source_returns,
        }
    ).to_parquet(source, index=False)
    path.write_text(
        json.dumps(
            {
                "name": name,
                "signal": signal,
                "portfolio_weight_max": 0.10,
                "sharpe_lower_ci_2_5": 0.5035,
                "sharpe_median_50": 1.8812,
                "sharpe_upper_ci_97_5": 3.3224,
                "source_parquet": str(source),
            }
        ),
        encoding="utf-8",
    )
    return path
