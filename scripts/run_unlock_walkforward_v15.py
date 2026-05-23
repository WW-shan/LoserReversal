"""Run Phase 1.5 unlock walk-forward validation across all signal versions."""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from infra.backtest.walkforward import walk_forward_splits
from infra.storage import read_unlocks
from signals.unlock_grid import SIGNAL_REGISTRY
from signals.unlock_walkforward import compose_portfolio, run_per_signal_walkforward

if __package__:
    from scripts.sweep_unlock_grid_v15 import load_coverage, load_prices
else:
    from sweep_unlock_grid_v15 import load_coverage, load_prices


DEFAULT_OUT = Path("data/parquet/phase1_5_walkforward.parquet")
DEFAULT_REPORT = Path("reports/phase1_5_walkforward.md")
DEFAULT_UNLOCKS_PATH = Path("data/parquet/unlocks.parquet")
DEFAULT_COVERAGE_PATH = Path("data/parquet/event_coverage.parquet")
DEFAULT_CANDLES_DIR = Path("data/parquet/candles")
DEFAULT_GRID_PATH = Path("data/parquet/unlock_grid_v15.parquet")
DEFAULT_N_SPLITS = 5
DEFAULT_MIN_TRAIN_DAYS = 270
DEFAULT_TEST_DAYS = 180
MIN_RECOMMENDED_COVERAGE_PCT = 80.0
OUTPUT_COLUMNS = [
    "kind",
    "signal",
    "split_idx",
    "train_start",
    "train_end",
    "test_start",
    "test_end",
    "selected_min_pct",
    "selected_cohort",
    "n_trades",
    "sharpe",
    "sortino",
    "win_rate",
    "max_dd",
    "total_return",
    "fallback_used",
]
OUTPUT_SCHEMA = pa.schema(
    [
        ("kind", pa.string()),
        ("signal", pa.string()),
        ("split_idx", pa.int64()),
        ("train_start", pa.timestamp("us", tz="UTC")),
        ("train_end", pa.timestamp("us", tz="UTC")),
        ("test_start", pa.timestamp("us", tz="UTC")),
        ("test_end", pa.timestamp("us", tz="UTC")),
        ("selected_min_pct", pa.float64()),
        ("selected_cohort", pa.string()),
        ("n_trades", pa.int64()),
        ("sharpe", pa.float64()),
        ("sortino", pa.float64()),
        ("win_rate", pa.float64()),
        ("max_dd", pa.float64()),
        ("total_return", pa.float64()),
        ("fallback_used", pa.bool_()),
    ]
)


@dataclass(frozen=True)
class WalkForwardV15Config:
    n_splits: int = DEFAULT_N_SPLITS
    mode: str = "expanding"
    min_train_days: int = DEFAULT_MIN_TRAIN_DAYS
    test_days: int = DEFAULT_TEST_DAYS
    top_k: int = 2
    out: Path = DEFAULT_OUT
    report: Path = DEFAULT_REPORT
    init_cash: float = 10_000.0
    fees: float = 0.0005
    slippage: float = 0.0002
    unlocks_path: Path = DEFAULT_UNLOCKS_PATH
    coverage_path: Path = DEFAULT_COVERAGE_PATH
    candles_dir: Path = DEFAULT_CANDLES_DIR
    grid_path: Path = DEFAULT_GRID_PATH


def run_walkforward(config: WalkForwardV15Config) -> dict[str, Any]:
    events = _load_candidate_events(config.unlocks_path)
    if events.empty:
        raise RuntimeError("no has_hl_perp unlock events available")

    coverage = load_coverage(config.coverage_path)
    prices = load_prices(events, config.candles_dir)
    grid_df = pd.read_parquet(config.grid_path)
    start = events["unlock_date"].min().to_pydatetime()
    end = events["unlock_date"].max().to_pydatetime()
    _log_walkforward_span(config, start, end)
    splits, effective_test_days, fallback_used = _walk_forward_splits_with_test_day_fallback(
        start=start,
        end=end,
        n_splits=config.n_splits,
        mode=config.mode,
        min_train_days=config.min_train_days,
        test_days=config.test_days,
    )

    per_signal = run_per_signal_walkforward(
        events,
        prices,
        coverage,
        splits,
        list(SIGNAL_REGISTRY),
        grid_df=grid_df,
        init_cash=config.init_cash,
        fees=config.fees,
        slippage=config.slippage,
        fallback_used=fallback_used,
    )
    portfolio = compose_portfolio(
        per_signal,
        events,
        prices,
        coverage,
        splits,
        top_k=config.top_k,
        init_cash=config.init_cash,
        fees=config.fees,
        slippage=config.slippage,
    )
    frame = pd.concat([per_signal, portfolio], ignore_index=True)

    _write_parquet(frame, config.out)
    _write_report(config.report, frame, grid_df, config, effective_test_days, fallback_used)
    print(f"wrote parquet: {config.out}")
    print(f"wrote report: {config.report}")
    return {
        "frame": frame,
        "out": config.out,
        "report": config.report,
        "effective_test_days": effective_test_days,
        "fallback_used": fallback_used,
    }


def _load_candidate_events(path: Path) -> pd.DataFrame:
    events = read_unlocks(path)
    if events.empty or "unlock_date" not in events.columns:
        return events.iloc[0:0].copy()

    frame = events.copy()
    if "has_hl_perp" in frame.columns:
        frame = frame.loc[_coerce_bool_series(frame["has_hl_perp"])].copy()
    frame["unlock_date"] = pd.to_datetime(frame["unlock_date"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["unlock_date"])
    return frame.sort_values("unlock_date").reset_index(drop=True)


def _walk_forward_splits_with_test_day_fallback(
    *,
    start: datetime,
    end: datetime,
    n_splits: int,
    mode: str,
    min_train_days: int,
    test_days: int,
) -> tuple[list[tuple[tuple[datetime, datetime], tuple[datetime, datetime]]], int, bool]:
    last_error: ValueError | None = None
    for candidate_test_days in _test_day_candidates(test_days):
        try:
            splits = walk_forward_splits(
                start,
                end,
                n_splits=n_splits,
                mode=mode,
                min_train_days=min_train_days,
                test_days=candidate_test_days,
            )
        except ValueError as error:
            last_error = error
            continue
        fallback_used = candidate_test_days != test_days
        if fallback_used:
            _log(
                "[WARN] walk-forward split infeasible with "
                f"test_days={test_days}; using test_days={candidate_test_days}"
            )
        return splits, candidate_test_days, fallback_used

    detail = f": {last_error}" if last_error is not None else ""
    raise RuntimeError(f"walk-forward split infeasible for available data span{detail}")


def _test_day_candidates(test_days: int) -> list[int]:
    candidates = [test_days]
    for fallback in (60, 30):
        if fallback < test_days and fallback not in candidates:
            candidates.append(fallback)
    return candidates


def _log_walkforward_span(
    config: WalkForwardV15Config,
    start: datetime,
    end: datetime,
) -> None:
    requested_days = config.min_train_days + config.n_splits * config.test_days
    span_days = max((end - start).days, 0)
    coverage_pct = (requested_days / span_days * 100.0) if span_days else 0.0
    _log(
        f"walk-forward span: train_days={config.min_train_days} + "
        f"n_splits×test_days = {requested_days} days; data span = {span_days} days; "
        f"coverage = {coverage_pct:.1f}%"
    )
    if coverage_pct < MIN_RECOMMENDED_COVERAGE_PCT:
        _log(
            "[WARNING] walk-forward coverage below 80%; recommended params: "
            f"--n-splits {DEFAULT_N_SPLITS} "
            f"--min-train-days {DEFAULT_MIN_TRAIN_DAYS} "
            f"--test-days {DEFAULT_TEST_DAYS}"
        )


def _write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    output = _normalize_output_frame(frame)
    table = pa.Table.from_pandas(output, schema=OUTPUT_SCHEMA, preserve_index=False)
    pq.write_table(table, path, coerce_timestamps="us")


def _normalize_output_frame(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    for column in OUTPUT_COLUMNS:
        if column not in output.columns:
            output[column] = pd.NA
    output = output[OUTPUT_COLUMNS]
    for column in ["kind", "signal", "selected_cohort"]:
        output[column] = output[column].astype("string")
    for column in ["train_start", "train_end", "test_start", "test_end"]:
        output[column] = pd.to_datetime(output[column], utc=True, errors="coerce")
    output["split_idx"] = pd.to_numeric(output["split_idx"], errors="coerce").fillna(-1).astype("int64")
    output["selected_min_pct"] = pd.to_numeric(output["selected_min_pct"], errors="coerce")
    for column in ["n_trades"]:
        output[column] = pd.to_numeric(output[column], errors="coerce").fillna(0).astype("int64")
    for column in ["sharpe", "sortino", "win_rate", "max_dd", "total_return"]:
        output[column] = pd.to_numeric(output[column], errors="coerce").astype("float64")
    output["fallback_used"] = output["fallback_used"].fillna(False).astype("bool")
    return output


def _write_report(
    path: Path,
    frame: pd.DataFrame,
    grid_df: pd.DataFrame,
    config: WalkForwardV15Config,
    effective_test_days: int,
    fallback_used: bool,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    generated = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Phase 1.5 Unlock Walk-Forward",
        "",
        f"_Generated {generated}_",
        "",
        "## Methodology",
        "",
        *_methodology_lines(config, effective_test_days, fallback_used),
        "",
        "## Per-Signal Walk-Forward",
        "",
        *_per_signal_table(frame, grid_df),
        "",
        "## Portfolio Walk-Forward",
        "",
        *_portfolio_table(frame),
        "",
        "## Best-Signal Snapshot",
        "",
        *_best_signal_snapshot(frame),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _methodology_lines(
    config: WalkForwardV15Config,
    effective_test_days: int,
    fallback_used: bool,
) -> list[str]:
    return [
        f"- Walk-forward uses {config.n_splits} {config.mode} splits with "
        f"{config.min_train_days} train days and {effective_test_days} OOS test days.",
        "- Each signal is tuned independently inside the train fold by rerunning "
        "min_unlock_pct/cohort cells and requiring n_trades >= 15.",
        "- If no train cell reaches 15 trades, selection falls back to the best "
        "positive-trade train cell, then max-Sharpe zero-trade only as a last resort.",
        "- OOS rows apply the train-selected config to test-window events only.",
        f"- The portfolio selects top-{config.top_k} signals by aggregate OOS Sharpe and "
        "combines component stats with equal weights.",
        f"- test_days fallback_used: {_fmt_bool(fallback_used)}.",
    ]


def _per_signal_table(frame: pd.DataFrame, grid_df: pd.DataFrame) -> list[str]:
    split_rows = frame.loc[frame["kind"].eq("per_signal") & frame["split_idx"].ge(0)]
    aggregate_rows = frame.loc[frame["kind"].eq("per_signal") & frame["split_idx"].eq(-1)]
    lines = [
        "| signal | mean OOS Sharpe | total n_trades | mean win_rate | "
        "mean max_dd | IS-vs-OOS decay |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    if aggregate_rows.empty:
        lines.append("| - | - | - | - | - | - |")
        return lines

    for row in aggregate_rows.sort_values("sharpe", ascending=False).to_dict("records"):
        signal = str(row["signal"])
        signal_splits = split_rows.loc[split_rows["signal"].eq(signal)]
        lines.append(
            f"| {signal} | {_fmt_num(row['sharpe'], 2)} | {int(row['n_trades'])} | "
            f"{_fmt_pct(signal_splits['win_rate'].mean())} | "
            f"{_fmt_pct(signal_splits['max_dd'].mean())} | "
            f"{_fmt_pct(_is_oos_decay(_best_is_sharpe(grid_df, signal), row['sharpe']))} |"
        )
    return lines


def _portfolio_table(frame: pd.DataFrame) -> list[str]:
    rows = frame.loc[frame["kind"].eq("portfolio") & frame["split_idx"].eq(-1)]
    lines = [
        "| portfolio | combined Sharpe | n_trades | win_rate | max_dd | total_return |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    if rows.empty:
        lines.append("| - | - | - | - | - | - |")
        return lines

    for row in rows.sort_values("sharpe", ascending=False).to_dict("records"):
        lines.append(
            f"| {row['signal']} | {_fmt_num(row['sharpe'], 2)} | {int(row['n_trades'])} | "
            f"{_fmt_pct(row['win_rate'])} | {_fmt_pct(row['max_dd'])} | "
            f"{_fmt_pct(row['total_return'])} |"
        )
    return lines


def _best_signal_snapshot(frame: pd.DataFrame) -> list[str]:
    rows = frame.loc[frame["kind"].eq("per_signal") & frame["split_idx"].eq(-1)]
    if rows.empty:
        return ["No per-signal aggregate rows were produced."]

    best = rows.sort_values("sharpe", ascending=False).iloc[0]
    return [
        f"Best signal: {best['signal']} with OOS Sharpe {_fmt_num(best['sharpe'], 2)} "
        f"and {int(best['n_trades'])} OOS trades.",
    ]


def _best_is_sharpe(grid_df: pd.DataFrame, signal: str) -> float:
    if grid_df.empty or not {"signal", "sharpe", "n_trades"}.issubset(grid_df.columns):
        return float("nan")
    rows = grid_df.loc[grid_df["signal"].eq(signal)].copy()
    eligible = rows.loc[rows["n_trades"].astype("int64").ge(30)]
    if not eligible.empty:
        rows = eligible
    if rows.empty:
        return float("nan")
    return float(rows["sharpe"].max())


def _is_oos_decay(is_sharpe: float, oos_sharpe: float) -> float:
    if not math.isfinite(is_sharpe) or math.isclose(is_sharpe, 0.0):
        return float("nan")
    return float((is_sharpe - float(oos_sharpe)) / is_sharpe)


def _coerce_bool_series(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.astype("bool")
    return series.astype("string").str.lower().isin({"true", "1", "1.0", "yes", "y", "t"})


def _fmt_bool(value: bool) -> str:
    return "yes" if value else "no"


def _fmt_pct(value: Any) -> str:
    number = float(value)
    if not math.isfinite(number):
        return "n/a"
    return f"{number * 100:.2f}%"


def _fmt_num(value: Any, decimals: int) -> str:
    number = float(value)
    if not math.isfinite(number):
        return "n/a"
    return f"{number:.{decimals}f}"


def _log(message: str) -> None:
    print(message, file=sys.stderr)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 1.5 unlock walk-forward.")
    parser.add_argument("--n-splits", type=int, default=DEFAULT_N_SPLITS)
    parser.add_argument("--mode", choices=["expanding", "rolling"], default="expanding")
    parser.add_argument("--min-train-days", type=int, default=DEFAULT_MIN_TRAIN_DAYS)
    parser.add_argument("--test-days", type=int, default=DEFAULT_TEST_DAYS)
    parser.add_argument("--top-k", type=int, default=2)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--init-cash", type=float, default=10_000.0)
    parser.add_argument("--fees", type=float, default=0.0005)
    parser.add_argument("--slippage", type=float, default=0.0002)
    args = parser.parse_args(argv)
    _validate_args(parser, args)
    return args


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.n_splits < 1:
        parser.error("--n-splits must be at least 1")
    if args.min_train_days < 1:
        parser.error("--min-train-days must be at least 1")
    if args.test_days < 1:
        parser.error("--test-days must be at least 1")
    if args.top_k < 1:
        parser.error("--top-k must be at least 1")
    if args.init_cash <= 0:
        parser.error("--init-cash must be greater than 0")
    if args.fees < 0:
        parser.error("--fees must be non-negative")
    if args.slippage < 0:
        parser.error("--slippage must be non-negative")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    config = WalkForwardV15Config(
        n_splits=args.n_splits,
        mode=args.mode,
        min_train_days=args.min_train_days,
        test_days=args.test_days,
        top_k=args.top_k,
        out=args.out,
        report=args.report,
        init_cash=args.init_cash,
        fees=args.fees,
        slippage=args.slippage,
    )
    try:
        run_walkforward(config)
    except RuntimeError as error:
        _log(f"error: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
