"""Tests for infrastructure backtest markdown reports."""

from pathlib import Path

import pandas as pd

from infra.backtest.engine import BacktestResult
from infra.report import write_backtest_report


def _fake_result() -> BacktestResult:
    index = pd.date_range("2026-01-01", periods=4, freq="1D", tz="UTC", name="timestamp")
    equity = pd.Series([10_000.0, 10_500.0, 9_500.0, 11_000.0], index=index)
    stats = {
        "sharpe": 1.2345,
        "sortino": 2.3456,
        "max_dd": -0.095238,
        "total_return": 0.10,
        "win_rate": 0.625,
        "n_trades": 8,
    }
    return BacktestResult(portfolio=object(), stats=stats, equity=equity)


def test_write_backtest_report_creates_parent_dirs_and_required_tables(tmp_path: Path):
    out = tmp_path / "nested" / "report.md"

    write_backtest_report(
        out,
        title="BTC SMA Test",
        config_summary={"symbol": "BTC", "interval": "1d", "days": 90},
        result=_fake_result(),
    )

    text = out.read_text()
    assert text.startswith("# BTC SMA Test\n")
    assert "_Generated " in text
    assert "## Config" in text
    assert "| Key | Value |" in text
    assert "| symbol | BTC |" in text
    assert "| interval | 1d |" in text
    assert "## Stats" in text
    assert "| Sharpe | 1.23 |" in text
    assert "| Sortino | 2.35 |" in text
    assert "| Max DD | -9.52% |" in text
    assert "| total return | 10.00% |" in text
    assert "| win rate | 62.50% |" in text
    assert "| n_trades | 8 |" in text
    assert "| final equity | 11000.00 |" in text


def test_write_backtest_report_includes_equity_curve_summary(tmp_path: Path):
    out = tmp_path / "report.md"

    write_backtest_report(
        out,
        title="Equity Summary",
        config_summary={"symbol": "ETH"},
        result=_fake_result(),
    )

    text = out.read_text()
    assert "## Equity Curve Summary" in text
    assert "| First | 2026-01-01 00:00 UTC | 10000.00 |" in text
    assert "| Last | 2026-01-04 00:00 UTC | 11000.00 |" in text
    assert "| Min | 2026-01-03 00:00 UTC | 9500.00 |" in text
    assert "| Max | 2026-01-04 00:00 UTC | 11000.00 |" in text
