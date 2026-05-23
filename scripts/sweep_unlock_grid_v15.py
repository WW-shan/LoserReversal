"""Run the Phase 1.5 unlock signal grid sweep."""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from infra.storage import read_unlocks
from signals.unlock_grid import iter_grid, run_cell


DEFAULT_OUT = Path("data/parquet/unlock_grid_v15.parquet")
DEFAULT_REPORT = Path("reports/phase1_5_grid_sweep.md")
DEFAULT_UNLOCKS_PATH = Path("data/parquet/unlocks.parquet")
DEFAULT_COVERAGE_PATH = Path("data/parquet/event_coverage.parquet")
DEFAULT_CANDLES_DIR = Path("data/parquet/candles")


@dataclass(frozen=True)
class GridSweepConfig:
    out: Path = DEFAULT_OUT
    report: Path = DEFAULT_REPORT
    init_cash: float = 10_000.0
    fees: float = 0.0005
    slippage: float = 0.0002
    date_start: pd.Timestamp | None = None
    date_end: pd.Timestamp | None = None
    unlocks_path: Path = DEFAULT_UNLOCKS_PATH
    coverage_path: Path = DEFAULT_COVERAGE_PATH
    candles_dir: Path = DEFAULT_CANDLES_DIR


def run_sweep(config: GridSweepConfig) -> dict[str, Any]:
    events = _filter_events_by_date(
        read_unlocks(config.unlocks_path),
        date_start=config.date_start,
        date_end=config.date_end,
    )
    coverage = load_coverage(config.coverage_path)
    prices = load_prices(events, config.candles_dir)
    rows = run_main_grid(
        events,
        prices,
        coverage,
        init_cash=config.init_cash,
        fees=config.fees,
        slippage=config.slippage,
    )

    frame = pd.DataFrame(rows)
    config.out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(config.out, index=False)
    _write_report(config.report, rows, config)
    top_table = _top5_table(rows)
    print(top_table)
    print(f"wrote parquet: {config.out}")
    print(f"wrote report: {config.report}")
    return {
        "rows": rows,
        "out": config.out,
        "report": config.report,
        "top5": top_table,
    }


def run_main_grid(
    events: pd.DataFrame,
    prices: dict[str, pd.Series],
    coverage: pd.DataFrame,
    *,
    init_cash: float,
    fees: float,
    slippage: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for cell in iter_grid():
        row = run_cell(
            events,
            prices,
            coverage,
            cell,
            init_cash=init_cash,
            fees=fees,
            slippage=slippage,
        )
        row["eligible"] = int(row["n_trades"]) >= 30
        rows.append(row)
    return rows


def load_coverage(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path)


def load_prices(events: pd.DataFrame, candles_dir: Path) -> dict[str, pd.Series]:
    if events.empty or "token" not in events.columns:
        return {}

    prices: dict[str, pd.Series] = {}
    tokens = sorted(str(token) for token in events["token"].dropna().unique())
    for token in tokens:
        path = candles_dir / f"{token}_1d.parquet"
        if not path.exists():
            continue
        frame = pd.read_parquet(path)
        if frame.empty or not {"timestamp", "close"}.issubset(frame.columns):
            continue
        timestamps = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
        close = pd.to_numeric(frame["close"], errors="coerce")
        series = pd.Series(close.to_numpy(dtype="float64"), index=timestamps, name="close").dropna()
        if not series.empty:
            prices[token] = series.sort_index()
    return prices


def _filter_events_by_date(
    events: pd.DataFrame,
    *,
    date_start: pd.Timestamp | None,
    date_end: pd.Timestamp | None,
) -> pd.DataFrame:
    frame = events.copy()
    if frame.empty or "unlock_date" not in frame.columns:
        return frame

    frame["unlock_date"] = pd.to_datetime(frame["unlock_date"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["unlock_date"])
    if date_start is not None:
        frame = frame.loc[frame["unlock_date"] >= date_start].copy()
    if date_end is not None:
        frame = frame.loc[frame["unlock_date"] <= date_end].copy()
    return frame.reset_index(drop=True)


def _write_report(path: Path, rows: list[dict[str, Any]], config: GridSweepConfig) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    generated = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    eligible_rows = _eligible_rows(rows)
    lines = [
        "# Phase 1.5 Unlock Grid Sweep",
        "",
        f"_Generated {generated}_",
        "",
        "## Config",
        "",
        "| key | value |",
        "| --- | --- |",
        f"| init_cash | {config.init_cash:.2f} |",
        f"| fees | {config.fees:.6f} |",
        f"| slippage | {config.slippage:.6f} |",
        f"| date_start | {_fmt_date(config.date_start)} |",
        f"| date_end | {_fmt_date(config.date_end)} |",
        "",
        "## Top-5 by Sharpe",
        "",
        _top5_table(rows),
        "",
        "## Eligible Summary",
        "",
        f"{len(eligible_rows)} of {len(rows)} rows are eligible (n_trades >= 30).",
        "",
        "## Per-Cohort Breakdown",
        "",
        "| cohort | rows | eligible | best_sharpe | total_trades |",
        "| --- | ---: | ---: | ---: | ---: |",
        *_cohort_breakdown_rows(rows),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _top5_table(rows: list[dict[str, Any]]) -> str:
    ranked = sorted(_eligible_rows(rows), key=_sort_sharpe, reverse=True)[:5]
    lines = [
        "Top-5 by Sharpe (eligible: n_trades >= 30)",
        "",
        "| rank | signal | min_pct | cohort | sharpe | n_trades | win_rate | max_dd | total_return |",
        "| ---: | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    if not ranked:
        lines.append("| - | - | - | - | - | - | - | - | - |")
        return "\n".join(lines)

    for rank, row in enumerate(ranked, start=1):
        lines.append(
            f"| {rank} | {row['signal']} | {float(row['min_unlock_pct']):.2f} | "
            f"{row['cohort']} | {_fmt_num(row['sharpe'], 2)} | {int(row['n_trades'])} | "
            f"{_fmt_pct(row['win_rate'])} | {_fmt_pct(row['max_dd'])} | "
            f"{_fmt_pct(row['total_return'])} |"
        )
    return "\n".join(lines)


def _cohort_breakdown_rows(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["| - | - | - | - | - |"]

    output: list[str] = []
    frame = pd.DataFrame(rows)
    for cohort, cohort_frame in frame.groupby("cohort", sort=True):
        eligible = cohort_frame.loc[cohort_frame["eligible"].astype(bool)]
        best_sharpe = eligible["sharpe"].max() if not eligible.empty else math.nan
        output.append(
            f"| {cohort} | {len(cohort_frame)} | {len(eligible)} | "
            f"{_fmt_num(best_sharpe, 2)} | {int(cohort_frame['n_trades'].sum())} |"
        )
    return output


def _eligible_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if bool(row.get("eligible")) and int(row["n_trades"]) >= 30]


def _sort_sharpe(row: dict[str, Any]) -> float:
    value = float(row["sharpe"])
    return value if math.isfinite(value) else float("-inf")


def _fmt_date(value: pd.Timestamp | None) -> str:
    if value is None:
        return "events.min/events.max"
    return value.strftime("%Y-%m-%d")


def _fmt_pct(value: Any) -> str:
    return f"{float(value) * 100:.2f}%"


def _fmt_num(value: Any, decimals: int) -> str:
    number = float(value)
    if not math.isfinite(number):
        return "n/a"
    return f"{number:.{decimals}f}"


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 1.5 unlock signal grid sweep.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--init-cash", type=float, default=10_000.0)
    parser.add_argument("--fees", type=float, default=0.0005)
    parser.add_argument("--slippage", type=float, default=0.0002)
    parser.add_argument("--date-start")
    parser.add_argument("--date-end")
    args = parser.parse_args(argv)
    _validate_args(parser, args)
    return args


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.init_cash <= 0:
        parser.error("--init-cash must be greater than 0")
    if args.fees < 0:
        parser.error("--fees must be non-negative")
    if args.slippage < 0:
        parser.error("--slippage must be non-negative")
    try:
        args.date_start = _parse_iso_timestamp(args.date_start)
        args.date_end = _parse_iso_timestamp(args.date_end)
    except ValueError as error:
        parser.error(str(error))


def _parse_iso_timestamp(value: str | None) -> pd.Timestamp | None:
    if value is None:
        return None
    timestamp = pd.Timestamp(value)
    if timestamp.tz is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    run_sweep(
        GridSweepConfig(
            out=args.out,
            report=args.report,
            init_cash=args.init_cash,
            fees=args.fees,
            slippage=args.slippage,
            date_start=args.date_start,
            date_end=args.date_end,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
