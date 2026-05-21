"""Markdown report writer for infrastructure backtest results."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from infra.backtest.engine import BacktestResult


def write_backtest_report(
    path: Path,
    title: str,
    config_summary: dict,
    result: BacktestResult,
) -> None:
    """Write a markdown report for a backtest result."""
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        f"# {title}",
        "",
        f"_Generated {now}_",
        "",
        "## Config",
        "",
        "| Key | Value |",
        "| --- | --- |",
        *_config_rows(config_summary),
        "",
        "## Stats",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        *_stats_rows(result),
        "",
        "## Equity Curve Summary",
        "",
        "| Point | Timestamp | Equity |",
        "| --- | --- | --- |",
        *_equity_rows(result.equity),
    ]

    path.write_text("\n".join(lines) + "\n")


def _config_rows(config_summary: dict) -> list[str]:
    return [f"| {key} | {value} |" for key, value in config_summary.items()]


def _stats_rows(result: BacktestResult) -> list[str]:
    stats = result.stats
    final_equity = result.equity.iloc[-1] if not result.equity.empty else None
    return [
        f"| Sharpe | {_fmt_num(stats.get('sharpe'), 2)} |",
        f"| Sortino | {_fmt_num(stats.get('sortino'), 2)} |",
        f"| Max DD | {_fmt_pct(stats.get('max_dd'))} |",
        f"| total return | {_fmt_pct(stats.get('total_return'))} |",
        f"| win rate | {_fmt_pct(stats.get('win_rate'))} |",
        f"| n_trades | {stats.get('n_trades', '-')} |",
        f"| final equity | {_fmt_num(final_equity, 2)} |",
    ]


def _equity_rows(equity: pd.Series) -> list[str]:
    if equity.empty:
        return [
            "| First | - | - |",
            "| Last | - | - |",
            "| Min | - | - |",
            "| Max | - | - |",
        ]

    points = [
        ("First", equity.index[0], equity.iloc[0]),
        ("Last", equity.index[-1], equity.iloc[-1]),
        ("Min", equity.idxmin(), equity.min()),
        ("Max", equity.idxmax(), equity.max()),
    ]
    return [f"| {label} | {_fmt_ts(ts)} | {_fmt_num(value, 2)} |" for label, ts, value in points]


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "-"
    return f"{float(value) * 100:.2f}%"


def _fmt_num(value: Any, decimals: int) -> str:
    if value is None:
        return "-"
    return f"{float(value):.{decimals}f}"


def _fmt_ts(value: Any) -> str:
    ts = pd.Timestamp(value)
    if ts.tz is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.strftime("%Y-%m-%d %H:%M UTC")
