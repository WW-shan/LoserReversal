"""Run a grid sweep for the unlock-short strategy."""

from __future__ import annotations

import argparse
import math
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from infra.pipeline import interval_timedelta

if __package__:
    from scripts.run_unlock_backtest import UnlockBacktestConfig, run_unlock_backtest
else:
    from run_unlock_backtest import UnlockBacktestConfig, run_unlock_backtest


PRE_WINDOW_GRID = (3, 5, 7, 10, 14)
MIN_UNLOCK_PCT_GRID = (0.01, 0.02, 0.03, 0.05)


def run_sweep(config: UnlockBacktestConfig) -> dict[str, Any]:
    started = time.perf_counter()
    rows: list[dict[str, Any]] = []
    grid = [
        (pre_window_days, min_unlock_pct)
        for pre_window_days in PRE_WINDOW_GRID
        for min_unlock_pct in MIN_UNLOCK_PCT_GRID
    ]

    for index, (pre_window_days, min_unlock_pct) in enumerate(grid, start=1):
        combo_started = time.perf_counter()
        result = run_unlock_backtest(
            replace(
                config,
                pre_window_days=pre_window_days,
                min_unlock_pct=min_unlock_pct,
                report=None,
            )
        )
        stats = result["portfolio_stats"]
        n_trades = int(stats["n_trades"])
        row = {
            "pre_window": pre_window_days,
            "min_pct": min_unlock_pct,
            "sharpe": float(stats["sharpe"]),
            "sortino": float(stats["sortino"]),
            "max_dd": float(stats["max_dd"]),
            "n_trades": n_trades,
            "eligible": n_trades >= 30,
            "win_rate": float(stats["win_rate"]),
            "total_return": float(stats["total_return"]),
        }
        rows.append(row)
        elapsed = time.perf_counter() - combo_started
        _log(
            f"[{index}/{len(grid)}] pre={pre_window_days} min={min_unlock_pct:.2f} "
            f"→ Sharpe={row['sharpe']:.2f} ({elapsed:.1f}s)"
        )

    ranked = sorted(rows, key=_sort_eligible_sharpe, reverse=True)
    output = {
        "rows": ranked,
        "total_combinations": len(grid),
        "runtime_seconds": time.perf_counter() - started,
        "report_path": config.report,
    }
    if config.report is not None:
        _write_sweep_report(config.report, output)
    return output


def _write_sweep_report(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    generated = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    rows = result["rows"]
    eligible_rows = [row for row in rows if row["eligible"]]
    best_eligible_sharpe = _fmt_num(eligible_rows[0]["sharpe"], 2) if eligible_rows else "n/a"

    lines = [
        "# Unlock Short V1 Parameter Sweep",
        "",
        f"_Generated {generated}_",
        "",
        "## Decision Gate Summary",
        "",
        f"{len(eligible_rows)} of {result['total_combinations']} combinations are eligible.",
        f"Best eligible Sharpe: {best_eligible_sharpe}",
        "",
        f"Total combinations: {result['total_combinations']}",
        f"Runtime seconds: {result['runtime_seconds']:.1f}",
        "",
        "## Eligible-only Ranking",
        "",
        *_eligible_ranking_rows(eligible_rows),
        "",
        "## Full Ranking",
        "",
        "| rank | eligible | pre_window | min_pct | sharpe | sortino | max_dd | n_trades | win_rate | total_return |",
        "| ---: | :---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        *_sweep_rows(rows),
    ]
    path.write_text("\n".join(lines) + "\n")


def _eligible_ranking_rows(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["No eligible rows (n_trades >= 30)."]

    return [
        "| rank | eligible | pre_window | min_pct | sharpe | sortino | max_dd | n_trades | win_rate | total_return |",
        "| ---: | :---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        *_sweep_rows(rows),
    ]


def _sweep_rows(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["| - | - | - | - | - | - | - | - | - | - |"]

    output = []
    for rank, row in enumerate(rows, start=1):
        output.append(
            f"| {rank} | {_fmt_bool(row['eligible'])} | "
            f"{row['pre_window']} | {row['min_pct']:.2f} | "
            f"{_fmt_num(row['sharpe'], 2)} | {_fmt_num(row['sortino'], 2)} | "
            f"{_fmt_pct(row['max_dd'])} | "
            f"{row['n_trades']} | {_fmt_pct(row['win_rate'])} | "
            f"{_fmt_pct(row['total_return'])} |"
        )
    return output


def _fmt_pct(value: Any) -> str:
    return f"{float(value) * 100:.2f}%"


def _fmt_num(value: Any, decimals: int) -> str:
    number = float(value)
    if not math.isfinite(number):
        return "n/a"
    return f"{number:.{decimals}f}"


def _fmt_bool(value: bool) -> str:
    return "yes" if value else "no"


def _sort_eligible_sharpe(row: dict[str, Any]) -> tuple[bool, float]:
    return bool(row["eligible"]), _sort_sharpe(row)


def _sort_sharpe(row: dict[str, Any]) -> float:
    value = float(row["sharpe"])
    return value if math.isfinite(value) else float("-inf")


def _log(message: str) -> None:
    print(message, file=sys.stderr)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sweep unlock-short strategy parameters.")
    parser.add_argument("--interval", default="1d")
    parser.add_argument("--init-cash", type=float, default=10_000.0)
    parser.add_argument("--fees", type=float, default=0.0005)
    parser.add_argument("--slippage", type=float, default=0.0002)
    parser.add_argument("--report", type=Path, default=Path("reports/unlock_v1_sweep.md"))
    args = parser.parse_args()
    _validate_args(parser, args)
    return args


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.init_cash <= 0:
        parser.error("--init-cash must be greater than 0")
    if args.fees < 0:
        parser.error("--fees must be non-negative")
    if args.slippage < 0:
        parser.error("--slippage must be non-negative")
    if not args.interval:
        parser.error("--interval must not be empty")
    try:
        interval_timedelta(args.interval)
    except ValueError as error:
        parser.error(str(error))


def main() -> int:
    args = _parse_args()
    config = UnlockBacktestConfig(
        interval=args.interval,
        init_cash=args.init_cash,
        fees=args.fees,
        slippage=args.slippage,
        report=args.report,
    )
    result = run_sweep(config)
    print(f"wrote report: {result['report_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
