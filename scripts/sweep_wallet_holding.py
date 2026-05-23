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
    from scripts.run_wallet_reverse_backtest import (
        WalletReverseBacktestConfig,
        run_wallet_reverse_backtest,
    )
else:
    from run_wallet_reverse_backtest import WalletReverseBacktestConfig, run_wallet_reverse_backtest


HOLDING_GRID = (1.0, 4.0, 12.0, 24.0)


def run_sweep(config: WalletReverseBacktestConfig) -> dict[str, Any]:
    started = time.perf_counter()
    rows: list[dict[str, Any]] = []

    for index, holding_hours in enumerate(HOLDING_GRID, start=1):
        combo_started = time.perf_counter()
        result = run_wallet_reverse_backtest(
            replace(config, holding_hours=holding_hours, report=None)
        )
        stats = result["portfolio_stats"]
        n_trades = int(stats["n_trades"])
        row = {
            "holding": holding_hours,
            "n_trades": n_trades,
            "trade_level_ir": float(stats["trade_level_ir"]),
            "sharpe": float(stats["sharpe"]),
            "sortino": float(stats["sortino"]),
            "max_dd": float(stats["max_dd"]),
            "total_return": float(stats["total_return"]),
            "win_rate": float(stats["win_rate"]),
            "eligible": n_trades >= 100,
        }
        rows.append(row)
        elapsed = time.perf_counter() - combo_started
        _log(
            f"[{index}/{len(HOLDING_GRID)}] holding={holding_hours:g}h "
            f"trades={n_trades} IR={row['trade_level_ir']:.2f} "
            f"Sharpe={row['sharpe']:.2f} ({elapsed:.1f}s)"
        )

    ranked = sorted(rows, key=_sort_eligible_sharpe, reverse=True)
    output = {
        "rows": ranked,
        "total_combinations": len(HOLDING_GRID),
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
    best = eligible_rows[0] if eligible_rows else (rows[0] if rows else None)

    lines = [
        "# Wallet Reverse V1 Holding-Time Sweep",
        "",
        f"_Generated {generated}_",
        "",
        "## Decision Gate Summary",
        "",
        f"{len(eligible_rows)} of {result['total_combinations']} holding windows are eligible.",
        f"Best holding by Sharpe: {_best_summary(best)}",
        f"Runtime seconds: {result['runtime_seconds']:.1f}",
        "",
        "## Sweep Results",
        "",
        "| holding | n_trades | trade_level_ir | sharpe | sortino | max_dd | total_return | win_rate | eligible |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: |",
        *_sweep_rows(rows),
    ]
    path.write_text("\n".join(lines) + "\n")


def _sweep_rows(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["| - | - | - | - | - | - | - | - | - |"]
    return [
        f"| {row['holding']:g}h | {row['n_trades']} | "
        f"{_fmt_num(row['trade_level_ir'], 2)} | {_fmt_num(row['sharpe'], 2)} | "
        f"{_fmt_num(row['sortino'], 2)} | {_fmt_pct(row['max_dd'])} | "
        f"{_fmt_pct(row['total_return'])} | {_fmt_pct(row['win_rate'])} | "
        f"{_fmt_bool(row['eligible'])} |"
        for row in rows
    ]


def _best_summary(row: dict[str, Any] | None) -> str:
    if row is None:
        return "n/a"
    return f"{row['holding']:g}h (Sharpe {_fmt_num(row['sharpe'], 2)}, {row['n_trades']} trades)"


def _sort_eligible_sharpe(row: dict[str, Any]) -> tuple[bool, float]:
    return bool(row["eligible"]), _sort_sharpe(row)


def _sort_sharpe(row: dict[str, Any]) -> float:
    value = float(row["sharpe"])
    return value if math.isfinite(value) else float("-inf")


def _fmt_pct(value: Any) -> str:
    return f"{float(value) * 100:.2f}%"


def _fmt_num(value: Any, decimals: int) -> str:
    number = float(value)
    if not math.isfinite(number):
        return "n/a"
    return f"{number:.{decimals}f}"


def _fmt_bool(value: bool) -> str:
    return "yes" if value else "no"


def _log(message: str) -> None:
    print(message, file=sys.stderr)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sweep wallet reverse holding times.")
    parser.add_argument("--top-wallet-n", type=int, default=50)
    parser.add_argument("--candle-interval", default="1h")
    parser.add_argument("--init-cash", type=float, default=10_000.0)
    parser.add_argument("--fees", type=float, default=0.0005)
    parser.add_argument("--slippage", type=float, default=0.0002)
    parser.add_argument("--report", type=Path, default=Path("reports/wallet_reverse_v1_sweep.md"))
    args = parser.parse_args()
    _validate_args(parser, args)
    return args


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.top_wallet_n <= 0:
        parser.error("--top-wallet-n must be greater than 0")
    if args.init_cash <= 0:
        parser.error("--init-cash must be greater than 0")
    if args.fees < 0:
        parser.error("--fees must be non-negative")
    if args.slippage < 0:
        parser.error("--slippage must be non-negative")
    if not args.candle_interval:
        parser.error("--candle-interval must not be empty")
    try:
        interval_timedelta(args.candle_interval)
    except ValueError as error:
        parser.error(str(error))


def main() -> int:
    args = _parse_args()
    result = run_sweep(
        WalletReverseBacktestConfig(
            top_wallet_n=args.top_wallet_n,
            candle_interval=args.candle_interval,
            init_cash=args.init_cash,
            fees=args.fees,
            slippage=args.slippage,
            report=args.report,
        )
    )
    print(f"wrote report: {result['report_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
