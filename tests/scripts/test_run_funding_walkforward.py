from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from scripts import run_funding_walkforward as cli


def test_cli_smoke_writes_parquet_and_report(tmp_path: Path):
    funding_dir = tmp_path / "funding"
    candles_dir = tmp_path / "candles"
    out = tmp_path / "funding_walkforward.parquet"
    report = tmp_path / "funding_walkforward.md"
    _write_fixture(funding_dir, candles_dir)

    exit_code = cli.main(
        [
            "--funding-dir",
            str(funding_dir),
            "--candles-dir",
            str(candles_dir),
            "--out",
            str(out),
            "--report",
            str(report),
            "--n-splits",
            "2",
            "--train-days",
            "120",
            "--test-days",
            "60",
            "--min-is-trades",
            "1",
            "--taker-fee",
            "0",
            "--slippage",
            "0",
        ]
    )

    assert exit_code == 0
    assert out.exists()
    assert report.exists()
    text = report.read_text(encoding="utf-8")
    assert "Phase 3 Funding Extreme Contrarian Walk-Forward" in text
    assert "Verdict:" in text
    frame = pd.read_parquet(out)
    assert (frame["split_idx"] == -1).any()


def test_cli_argument_validation_rejects_zero_splits(tmp_path: Path, capsys):
    funding_dir = tmp_path / "funding"
    candles_dir = tmp_path / "candles"
    _write_fixture(funding_dir, candles_dir)
    try:
        cli.main(
            [
                "--funding-dir",
                str(funding_dir),
                "--candles-dir",
                str(candles_dir),
                "--out",
                str(tmp_path / "out.parquet"),
                "--report",
                str(tmp_path / "report.md"),
                "--n-splits",
                "0",
            ]
        )
    except SystemExit as exc:
        assert exc.code == 2
    err = capsys.readouterr().err
    assert "--n-splits" in err


def test_cli_file_execution_smoke(tmp_path: Path):
    funding_dir = tmp_path / "funding"
    candles_dir = tmp_path / "candles"
    out = tmp_path / "funding_walkforward.parquet"
    report = tmp_path / "funding_walkforward.md"
    _write_fixture(funding_dir, candles_dir)

    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_funding_walkforward.py",
            "--funding-dir",
            str(funding_dir),
            "--candles-dir",
            str(candles_dir),
            "--out",
            str(out),
            "--report",
            str(report),
            "--n-splits",
            "2",
            "--train-days",
            "120",
            "--test-days",
            "60",
            "--min-is-trades",
            "1",
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
    assert report.exists()


def test_cli_accepts_price_interval_flag(monkeypatch, tmp_path: Path):
    """`--price-interval 4h` is forwarded to the run() entrypoint."""
    captured: dict[str, object] = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return {"frame": pd.DataFrame(), "verdict": "RED", "out": kwargs["out"], "report": kwargs["report"]}

    monkeypatch.setattr(cli, "run", fake_run)

    exit_code = cli.main(
        [
            "--funding-dir",
            str(tmp_path / "funding"),
            "--candles-dir",
            str(tmp_path / "candles"),
            "--out",
            str(tmp_path / "out.parquet"),
            "--report",
            str(tmp_path / "report.md"),
            "--n-splits",
            "2",
            "--train-days",
            "120",
            "--test-days",
            "60",
            "--price-interval",
            "4h",
        ]
    )

    assert exit_code == 0
    assert captured["price_interval"] == "4h"


def test_cli_default_price_interval_is_1h(monkeypatch, tmp_path: Path):
    """Walk-forward CLI default stays 1h for back-compat."""
    captured: dict[str, object] = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return {"frame": pd.DataFrame(), "verdict": "RED", "out": kwargs["out"], "report": kwargs["report"]}

    monkeypatch.setattr(cli, "run", fake_run)

    cli.main(
        [
            "--funding-dir",
            str(tmp_path / "funding"),
            "--candles-dir",
            str(tmp_path / "candles"),
            "--out",
            str(tmp_path / "out.parquet"),
            "--report",
            str(tmp_path / "report.md"),
            "--n-splits",
            "2",
            "--train-days",
            "120",
            "--test-days",
            "60",
        ]
    )

    assert captured["price_interval"] == "1h"


def test_run_walkforward_uses_4h_when_configured(tmp_path: Path, mocker):
    """Walk-forward must select 4h candles when --price-interval 4h is set."""
    funding_dir = tmp_path / "funding"
    candles_dir = tmp_path / "candles"
    _write_4h_only_fixture(funding_dir, candles_dir)

    out = tmp_path / "wf.parquet"
    report = tmp_path / "wf.md"

    exit_code = cli.main(
        [
            "--funding-dir",
            str(funding_dir),
            "--candles-dir",
            str(candles_dir),
            "--out",
            str(out),
            "--report",
            str(report),
            "--n-splits",
            "2",
            "--train-days",
            "120",
            "--test-days",
            "60",
            "--min-is-trades",
            "1",
            "--taker-fee",
            "0",
            "--slippage",
            "0",
            "--price-interval",
            "4h",
        ]
    )

    assert exit_code == 0
    assert out.exists()
    # If 4h selection failed the run would raise "no funding/price overlap".
    frame = pd.read_parquet(out)
    assert (frame["split_idx"] == -1).any()


def _write_fixture(funding_dir: Path, candles_dir: Path) -> None:
    funding_dir.mkdir(parents=True)
    candles_dir.mkdir(parents=True)
    hours = 24 * 300
    timestamps = pd.date_range("2024-01-01T00:00:00Z", periods=hours, freq="1h", tz="UTC")
    rates = np.full(hours, 0.0001, dtype="float64")
    for day in range(7, 300, 14):
        spike_start = day * 24
        for i in range(spike_start, min(spike_start + 6, hours)):
            rates[i] = 0.0015

    base_price = np.linspace(100.0, 130.0, hours, dtype="float64")
    noise = np.sin(np.arange(hours) / 100.0) * 2.0
    close = base_price + noise

    for token in ("BTC", "ETH"):
        pd.DataFrame(
            {
                "timestamp": timestamps,
                "funding_rate": rates,
                "premium": np.linspace(0.0, 0.001, hours),
            }
        ).to_parquet(funding_dir / f"{token}.parquet", index=False)

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


def _write_4h_only_fixture(funding_dir: Path, candles_dir: Path) -> None:
    """Same shape as `_write_fixture` but only 4h candles exist (no 1h parquets)."""
    funding_dir.mkdir(parents=True)
    candles_dir.mkdir(parents=True)
    days = 300
    bars_4h = days * 6  # 6 four-hour bars per day
    timestamps_4h = pd.date_range("2024-01-01T00:00:00Z", periods=bars_4h, freq="4h", tz="UTC")
    timestamps_8h = pd.date_range("2024-01-01T00:00:00Z", periods=days * 3, freq="8h", tz="UTC")

    rates = np.full(len(timestamps_8h), 0.0001, dtype="float64")
    for day in range(7, days, 14):
        idx = day * 3  # 3 funding ticks per day at 8h cadence
        for i in range(idx, min(idx + 3, len(rates))):
            rates[i] = 0.0015

    base_price = np.linspace(100.0, 130.0, bars_4h, dtype="float64")
    noise = np.sin(np.arange(bars_4h) / 50.0) * 2.0
    close = base_price + noise

    for token in ("BTC", "ETH"):
        pd.DataFrame(
            {
                "timestamp": timestamps_8h,
                "funding_rate": rates,
                "premium": np.linspace(0.0, 0.001, len(timestamps_8h)),
            }
        ).to_parquet(funding_dir / f"{token}.parquet", index=False)

        pd.DataFrame(
            {
                "timestamp": timestamps_4h,
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 1.0,
            }
        ).to_parquet(candles_dir / f"{token}_4h.parquet", index=False)
