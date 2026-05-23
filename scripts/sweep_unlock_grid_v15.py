"""Run the Phase 1.5 unlock signal grid sweep."""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from infra.storage import read_unlocks
from signals.unlock_grid import GridCell, iter_grid, run_cell


DEFAULT_OUT = Path("data/parquet/unlock_grid_v15.parquet")
DEFAULT_REPORT = Path("reports/phase1_5_grid_sweep.md")
DEFAULT_UNLOCKS_PATH = Path("data/parquet/unlocks.parquet")
DEFAULT_COVERAGE_PATH = Path("data/parquet/event_coverage.parquet")
DEFAULT_CANDLES_DIR = Path("data/parquet/candles")
VESTING_TYPES = ("cliff", "step", "linear")


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
    main_rows = run_main_grid(
        events,
        prices,
        coverage,
        init_cash=config.init_cash,
        fees=config.fees,
        slippage=config.slippage,
    )
    rows = [
        *main_rows,
        *run_vesting_sub_sweep(
            events,
            prices,
            coverage,
            main_rows,
            init_cash=config.init_cash,
            fees=config.fees,
            slippage=config.slippage,
        ),
    ]

    frame = pd.DataFrame(rows)
    config.out.parent.mkdir(parents=True, exist_ok=True)
    _write_parquet(frame, config.out, config)
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


def run_vesting_sub_sweep(
    events: pd.DataFrame,
    prices: dict[str, pd.Series],
    coverage: pd.DataFrame,
    main_rows: list[dict[str, Any]],
    *,
    init_cash: float,
    fees: float,
    slippage: float,
) -> list[dict[str, Any]]:
    best_row = _best_main_row(main_rows)
    if best_row is None:
        return []

    cell = _cell_from_row(best_row)
    rows: list[dict[str, Any]] = []
    for vesting_type in VESTING_TYPES:
        vesting_events = _filter_events_by_vesting_type(events, vesting_type)
        row = run_cell(
            vesting_events,
            prices,
            coverage,
            cell,
            init_cash=init_cash,
            fees=fees,
            slippage=slippage,
        )
        row["cohort"] = f"vesting:{vesting_type}"
        row["eligible"] = int(row["n_trades"]) >= 30
        rows.append(row)
    return rows


def load_coverage(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path)


def _write_parquet(frame: pd.DataFrame, path: Path, config: GridSweepConfig) -> None:
    table = pa.Table.from_pandas(frame, preserve_index=False)
    metadata = dict(table.schema.metadata or {})
    metadata[b"methodology"] = _methodology_text(config).encode("utf-8")
    metadata[b"cell_budget_per_token"] = f"{config.init_cash:.2f}".encode("utf-8")
    pq.write_table(table.replace_schema_metadata(metadata), path)


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


def _filter_events_by_vesting_type(events: pd.DataFrame, vesting_type: str) -> pd.DataFrame:
    if events.empty or "vesting_type" not in events.columns:
        return events.iloc[0:0].copy()
    return events.loc[events["vesting_type"].astype("string").eq(vesting_type)].copy()


def _best_main_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None

    eligible = _eligible_rows(rows)
    if eligible:
        return max(eligible, key=_sort_sharpe)
    return max(rows, key=_sort_sharpe)


def _cell_from_row(row: dict[str, Any]) -> GridCell:
    for cell in iter_grid():
        if (
            cell.code == row["signal"]
            and abs(cell.min_unlock_pct - float(row["min_unlock_pct"])) < 1e-12
            and cell.cohort_name == row["cohort"]
        ):
            return cell
    raise RuntimeError(f"no grid cell matches row: {row!r}")


def _write_report(path: Path, rows: list[dict[str, Any]], config: GridSweepConfig) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    generated = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    eligible_rows = _eligible_rows(rows)
    lines = [
        "# Phase 1.5 Unlock Grid Sweep",
        "",
        f"_Generated {generated}_",
        "",
        "## Methodology",
        "",
        *_methodology_lines(config),
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
        "## Vesting Sub-Sweep",
        "",
        *_vesting_sub_sweep_rows(rows),
        "",
        "## Per-Cohort Breakdown",
        "",
        "| cohort | rows | eligible | best_sharpe | total_trades |",
        "| --- | ---: | ---: | ---: | ---: |",
        *_cohort_breakdown_rows(rows),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _methodology_lines(config: GridSweepConfig) -> list[str]:
    return [
        f"- Each token's signal is backtested independently with ${config.init_cash:,.2f} "
        "starting capital.",
        "- Portfolio equity is the sum of per-token equities at each timestamp.",
        "- Inactive tokens contribute zero (no flat-cash padding).",
        "- Total return is relative to summed initial capital, NOT to a single $10k account.",
        "- This is an active-capital view; live deployment requires position sizing.",
    ]


def _methodology_text(config: GridSweepConfig) -> str:
    return "\n".join(line.removeprefix("- ") for line in _methodology_lines(config))


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


def _vesting_sub_sweep_rows(rows: list[dict[str, Any]]) -> list[str]:
    vesting_rows = [
        row for row in rows if str(row.get("cohort", "")).startswith("vesting:")
    ]
    lines = [
        "| vesting_type | n_trades | win_rate | sharpe | max_dd | total_return |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    if not vesting_rows:
        lines.append("| - | - | - | - | - | - |")
        return lines

    order = {vesting_type: index for index, vesting_type in enumerate(VESTING_TYPES)}
    for row in sorted(
        vesting_rows,
        key=lambda item: order.get(str(item["cohort"]).split("vesting:", maxsplit=1)[-1], 999),
    ):
        vesting_type = str(row["cohort"]).split("vesting:", maxsplit=1)[1]
        lines.append(
            f"| {vesting_type} | {int(row['n_trades'])} | {_fmt_pct(row['win_rate'])} | "
            f"{_fmt_num(row['sharpe'], 2)} | {_fmt_pct(row['max_dd'])} | "
            f"{_fmt_pct(row['total_return'])} |"
        )

    main_rows = [row for row in rows if not str(row.get("cohort", "")).startswith("vesting:")]
    best_row = _best_main_row(main_rows)
    if best_row is not None:
        lines.extend(
            [
                "",
                "Sub-sweep inherits config from the best main-grid cell "
                f"({best_row['signal']} / {float(best_row['min_unlock_pct']):.2f} / "
                f"{best_row['cohort']}). Eligibility threshold (n_trades ≥ 30) is "
                "informational only here.",
            ]
        )
    return lines


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
