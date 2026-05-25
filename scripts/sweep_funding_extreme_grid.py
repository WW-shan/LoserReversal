"""Run the 48-cell funding-extreme contrarian grid sweep."""

from __future__ import annotations

import argparse
import math
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from infra.storage import PARQUET_DIR

try:
    from scripts.run_funding_extreme_backtest import BacktestConfig, run_single_config
except ModuleNotFoundError:
    from run_funding_extreme_backtest import BacktestConfig, run_single_config


DEFAULT_OUT = PARQUET_DIR / "funding_extreme_grid.parquet"
DEFAULT_REPORT = Path("reports/funding_extreme_grid.md")
DEFAULT_FUNDING_DIR = PARQUET_DIR / "funding"
DEFAULT_CANDLES_DIR = PARQUET_DIR / "candles"
Z_THRESHOLDS = (1.5, 2.0, 2.5, 3.0)
HOLD_HOURS = (8, 24, 72, 168)
LOOKBACK_DAYS = (14, 30, 90)


@dataclass(frozen=True)
class GridCell:
    z_threshold: float
    hold_hours: int
    lookback_days: int


@dataclass(frozen=True)
class GridSweepConfig:
    funding_dir: Path = DEFAULT_FUNDING_DIR
    candles_dir: Path = DEFAULT_CANDLES_DIR
    out: Path = DEFAULT_OUT
    report: Path = DEFAULT_REPORT
    taker_fee: float = 0.0005
    slippage: float = 0.0002


def iter_grid() -> Iterator[GridCell]:
    for z_threshold in Z_THRESHOLDS:
        for hold_hours in HOLD_HOURS:
            for lookback_days in LOOKBACK_DAYS:
                yield GridCell(
                    z_threshold=z_threshold,
                    hold_hours=hold_hours,
                    lookback_days=lookback_days,
                )


def run_grid_sweep(config: GridSweepConfig) -> dict[str, Any]:
    frames = []
    for cell in iter_grid():
        frames.append(
            run_single_config(
                BacktestConfig(
                    funding_dir=config.funding_dir,
                    candles_dir=config.candles_dir,
                    z_threshold=cell.z_threshold,
                    hold_hours=cell.hold_hours,
                    lookback_days=cell.lookback_days,
                    taker_fee=config.taker_fee,
                    slippage=config.slippage,
                )
            )
        )

    frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    write_results(frame, config.out)
    write_report(config.report, frame, config)
    print(_top10_table(rank_aggregate_cells(frame)))
    print(f"wrote parquet: {config.out}")
    print(f"wrote report: {config.report}")
    return {"frame": frame, "ranking": rank_aggregate_cells(frame), "out": config.out}


def rank_aggregate_cells(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "token" not in frame:
        return pd.DataFrame()

    aggregate = frame.loc[frame["token"].eq("AGGREGATE")].copy()
    if aggregate.empty:
        return aggregate

    sort_sharpe = pd.to_numeric(aggregate["sharpe"], errors="coerce").fillna(float("-inf"))
    aggregate["_sort_sharpe"] = sort_sharpe
    aggregate["_sort_trades"] = pd.to_numeric(
        aggregate["n_trades"],
        errors="coerce",
    ).fillna(0)
    ranking = aggregate.sort_values(
        ["_sort_sharpe", "_sort_trades", "z_threshold", "hold_hours", "lookback_days"],
        ascending=[False, False, True, True, True],
        kind="mergesort",
    )
    return ranking.drop(columns=["_sort_sharpe", "_sort_trades"]).reset_index(drop=True)


def write_results(frame: pd.DataFrame, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(out, index=False)


def write_report(path: Path, frame: pd.DataFrame, config: GridSweepConfig) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_format_report(frame, config), encoding="utf-8")


def _format_report(frame: pd.DataFrame, config: GridSweepConfig) -> str:
    generated = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    ranking = rank_aggregate_cells(frame)
    lines = [
        "# Funding Extreme Contrarian Grid Sweep",
        "",
        f"_Generated {generated}_",
        "",
        "## Methodology",
        "",
        "- Each cell runs funding_extreme_signal for every token with matching 1h candles.",
        "- Funding payment is charged as sum(funding_rate x signed position) while held.",
        "- Aggregate equity sums per-token equity curves with equal per-token capital.",
        "",
        "## Config",
        "",
        "| key | value |",
        "| --- | --- |",
        f"| funding_dir | {config.funding_dir} |",
        f"| candles_dir | {config.candles_dir} |",
        f"| taker_fee | {config.taker_fee:.6f} |",
        f"| slippage | {config.slippage:.6f} |",
        "",
        "## Top-10 by Aggregate Sharpe",
        "",
        _top10_table(ranking),
        "",
        "## Best Per Token",
        "",
        *_best_per_token_rows(frame),
    ]
    return "\n".join(lines) + "\n"


def _top10_table(ranking: pd.DataFrame) -> str:
    lines = [
        "Top-10 by Aggregate Sharpe",
        "",
        "| rank | z | hold | lookback | n_trades | sharpe | annualized | max_dd | win_rate |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    if ranking.empty:
        lines.append("| - | - | - | - | - | - | - | - | - |")
        return "\n".join(lines)

    for rank, row in enumerate(ranking.head(10).to_dict("records"), start=1):
        lines.append(
            f"| {rank} | {float(row['z_threshold']):.1f} | {int(row['hold_hours'])} | "
            f"{int(row['lookback_days'])} | {int(row['n_trades'])} | "
            f"{_fmt_num(row['sharpe'], 2)} | {_fmt_pct(row['annualized_return'])} | "
            f"{_fmt_pct(row['max_dd'])} | {_fmt_pct(row['win_rate'])} |"
        )
    return "\n".join(lines)


def _best_per_token_rows(frame: pd.DataFrame) -> list[str]:
    lines = [
        "| token | z | hold | lookback | n_trades | sharpe | annualized | max_dd | win_rate |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    if frame.empty or "token" not in frame:
        lines.append("| - | - | - | - | - | - | - | - | - |")
        return lines

    token_rows = frame.loc[~frame["token"].eq("AGGREGATE")].copy()
    if token_rows.empty:
        lines.append("| - | - | - | - | - | - | - | - | - |")
        return lines

    token_rows["_sort_sharpe"] = pd.to_numeric(
        token_rows["sharpe"],
        errors="coerce",
    ).fillna(float("-inf"))
    token_rows["_sort_trades"] = pd.to_numeric(token_rows["n_trades"], errors="coerce").fillna(0)
    ordered = token_rows.sort_values(
        ["token", "_sort_sharpe", "_sort_trades"],
        ascending=[True, False, False],
        kind="mergesort",
    )
    best = ordered.drop_duplicates("token", keep="first")
    for row in best.to_dict("records"):
        lines.append(
            f"| {row['token']} | {float(row['z_threshold']):.1f} | {int(row['hold_hours'])} | "
            f"{int(row['lookback_days'])} | {int(row['n_trades'])} | "
            f"{_fmt_num(row['sharpe'], 2)} | {_fmt_pct(row['annualized_return'])} | "
            f"{_fmt_pct(row['max_dd'])} | {_fmt_pct(row['win_rate'])} |"
        )
    return lines


def _fmt_num(value: object, decimals: int) -> str:
    number = float(value)
    if not math.isfinite(number):
        return "n/a"
    return f"{number:.{decimals}f}"


def _fmt_pct(value: object) -> str:
    number = float(value)
    if not math.isfinite(number):
        return "n/a"
    return f"{number * 100:.2f}%"


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--funding-dir", type=Path, default=DEFAULT_FUNDING_DIR)
    parser.add_argument("--candles-dir", type=Path, default=DEFAULT_CANDLES_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--taker-fee", type=float, default=0.0005)
    parser.add_argument("--slippage", type=float, default=0.0002)
    args = parser.parse_args(argv)
    _validate_args(parser, args)
    return args


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.taker_fee < 0:
        parser.error("--taker-fee must be non-negative")
    if args.slippage < 0:
        parser.error("--slippage must be non-negative")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    run_grid_sweep(
        GridSweepConfig(
            funding_dir=args.funding_dir,
            candles_dir=args.candles_dir,
            out=args.out,
            report=args.report,
            taker_fee=args.taker_fee,
            slippage=args.slippage,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
