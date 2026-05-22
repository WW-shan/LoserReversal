"""Run walk-forward validation for the unlock-short strategy."""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from infra.backtest.walkforward import walk_forward_splits
from infra.pipeline import interval_timedelta
from infra.storage import read_unlocks

if __package__:
    from scripts.run_unlock_backtest import UnlockBacktestConfig, run_unlock_backtest
    from scripts.sweep_unlock_params import run_sweep
else:
    from run_unlock_backtest import UnlockBacktestConfig, run_unlock_backtest
    from sweep_unlock_params import run_sweep


IS_OOS_DECAY_LABEL = "IS\u2192OOS decay"


@dataclass(frozen=True)
class WalkForwardConfig:
    n_splits: int = 3
    mode: str = "expanding"
    min_train_days: int = 150
    test_days: int = 60
    interval: str = "1d"
    init_cash: float = 10_000.0
    fees: float = 0.0005
    slippage: float = 0.0002
    report: Path = Path("reports/unlock_v1_walkforward.md")


@dataclass(frozen=True)
class Verdict:
    label: str
    reason: str


def run_walkforward(config: WalkForwardConfig) -> dict[str, Any]:
    events = _load_candidate_events()
    if events.empty:
        raise RuntimeError("no has_hl_perp unlock events available")

    start = events["unlock_date"].min().to_pydatetime()
    end = events["unlock_date"].max().to_pydatetime()
    splits, effective_min_train_days = _walk_forward_splits_with_fallback(
        start=start,
        end=end,
        n_splits=config.n_splits,
        mode=config.mode,
        min_train_days=config.min_train_days,
        test_days=config.test_days,
    )

    split_results = []
    for index, split in enumerate(splits, start=1):
        _log(
            f"[split {index}/{len(splits)}] IS {_fmt_date(split[0][0])}.."
            f"{_fmt_date(split[0][1])} OOS {_fmt_date(split[1][0])}.."
            f"{_fmt_date(split[1][1])}"
        )
        split_results.append(_run_split(index, split, config))

    aggregate = _aggregate_split_results(split_results)
    verdict = _verdict(aggregate)
    result = {
        "config": config,
        "effective_min_train_days": effective_min_train_days,
        "data_span": {
            "start": start,
            "end": end,
            "total_days": int((end - start).days),
            "n_candidate_events": int(len(events)),
        },
        "split_results": split_results,
        "aggregate": aggregate,
        "verdict": verdict,
    }
    _write_report(config.report, result)
    return result


def _load_candidate_events() -> pd.DataFrame:
    events = read_unlocks()
    events = events.loc[_coerce_bool_series(events["has_hl_perp"])].copy()
    events["unlock_date"] = pd.to_datetime(events["unlock_date"], utc=True, errors="coerce")
    events = events.dropna(subset=["unlock_date"])
    return events.sort_values("unlock_date")


def _walk_forward_splits_with_fallback(
    *,
    start: datetime,
    end: datetime,
    n_splits: int,
    mode: str,
    min_train_days: int,
    test_days: int,
) -> tuple[list[tuple[tuple[datetime, datetime], tuple[datetime, datetime]]], int]:
    current_min_train_days = min_train_days
    min_floor = min(min_train_days, 90)
    last_error: ValueError | None = None

    while current_min_train_days >= min_floor:
        try:
            splits = walk_forward_splits(
                start,
                end,
                n_splits=n_splits,
                mode=mode,
                min_train_days=current_min_train_days,
                test_days=test_days,
            )
        except ValueError as error:
            last_error = error
            next_min_train_days = max(min_floor, current_min_train_days - 15)
            if next_min_train_days == current_min_train_days:
                break
            _log(
                "[WARN] walk-forward split infeasible with "
                f"min_train_days={current_min_train_days}: {error}; "
                f"retrying with min_train_days={next_min_train_days}"
            )
            current_min_train_days = next_min_train_days
            continue
        return splits, current_min_train_days

    detail = f": {last_error}" if last_error is not None else ""
    raise RuntimeError(f"walk-forward split infeasible for available data span{detail}")


def _run_split(
    split_index: int,
    split: tuple[tuple[datetime, datetime], tuple[datetime, datetime]],
    config: WalkForwardConfig,
) -> dict[str, Any]:
    (train_start, train_end), (test_start, test_end) = split
    train_config = UnlockBacktestConfig(
        interval=config.interval,
        init_cash=config.init_cash,
        fees=config.fees,
        slippage=config.slippage,
        date_start=train_start,
        date_end=train_end,
        report=None,
    )
    sweep = run_sweep(train_config)
    rows = sweep["rows"]
    if len(rows) != 20:
        _log(f"[WARN] split {split_index}: expected 20 sweep rows, got {len(rows)}")

    best_row, eligible_in_is, selection_mode = _select_best_is_row(rows, split_index)
    best_config = UnlockBacktestConfig(
        pre_window_days=int(best_row["pre_window"]),
        min_unlock_pct=float(best_row["min_pct"]),
        interval=config.interval,
        init_cash=config.init_cash,
        fees=config.fees,
        slippage=config.slippage,
        date_start=test_start,
        date_end=test_end,
        report=None,
    )
    oos_result = run_unlock_backtest(best_config)
    oos_stats = oos_result["portfolio_stats"]

    return {
        "split": split_index,
        "is_start": train_start,
        "is_end": train_end,
        "oos_start": test_start,
        "oos_end": test_end,
        "is_best_config": _config_label(best_row),
        "is_pre_window": int(best_row["pre_window"]),
        "is_min_pct": float(best_row["min_pct"]),
        "is_sharpe": float(best_row["sharpe"]),
        "is_n_trades": int(best_row["n_trades"]),
        "oos_sharpe": float(oos_stats["sharpe"]),
        "oos_n_trades": int(oos_stats["n_trades"]),
        "oos_max_dd": float(oos_stats["max_dd"]),
        "eligible_in_is": eligible_in_is,
        "is_selection_mode": selection_mode,
    }


def _select_best_is_row(
    rows: list[dict[str, Any]],
    split_index: int | None = None,
) -> tuple[dict[str, Any], bool, str]:
    if not rows:
        raise RuntimeError("parameter sweep returned no rows")

    eligible_rows = [row for row in rows if int(row["n_trades"]) >= 30]
    if eligible_rows:
        return max(eligible_rows, key=_sort_sharpe), True, "eligible"

    positive_trade_rows = [row for row in rows if int(row["n_trades"]) > 0]
    if positive_trade_rows:
        median_n_trades = _median_int(int(row["n_trades"]) for row in positive_trade_rows)
        median_bucket_rows = [
            row
            for row in positive_trade_rows
            if int(row["n_trades"]) >= median_n_trades and float(row["sharpe"]) > 0
        ]
        if median_bucket_rows:
            return (
                max(median_bucket_rows, key=_sort_sharpe),
                False,
                "positive_trades_median",
            )

        return max(positive_trade_rows, key=_sort_sharpe), False, "positive_trades_any"

    if split_index is not None:
        _log(
            f"[WARN] split {split_index}: no positive-trade IS config; "
            "fallback chose 0-trade max-Sharpe"
        )
    return max(rows, key=_sort_sharpe), False, "zero_trade_fallback"


def _aggregate_split_results(rows: list[dict[str, Any]]) -> dict[str, Any]:
    mean_is_sharpe = _mean([row["is_sharpe"] for row in rows])
    mean_oos_sharpe = _mean([row["oos_sharpe"] for row in rows])
    oos_max_dd_values = [float(row["oos_max_dd"]) for row in rows]
    return {
        "mean_is_sharpe": mean_is_sharpe,
        "oos_sharpe_mean": mean_oos_sharpe,
        "oos_sharpe_min": min(float(row["oos_sharpe"]) for row in rows),
        "oos_max_dd_worst": min(oos_max_dd_values) if oos_max_dd_values else 0.0,
        "oos_n_trades_total": sum(int(row["oos_n_trades"]) for row in rows),
        "is_oos_decay": _is_oos_decay(mean_is_sharpe, mean_oos_sharpe),
    }


def _verdict(aggregate: dict[str, Any]) -> Verdict:
    oos_sharpe_mean = float(aggregate["oos_sharpe_mean"])
    oos_n_trades_total = int(aggregate["oos_n_trades_total"])
    oos_max_dd_worst = float(aggregate["oos_max_dd_worst"])

    if oos_n_trades_total == 0:
        return Verdict("RED", "data_gap")
    if oos_n_trades_total < 15:
        return Verdict("RED", "insufficient_sample")
    if (
        math.isfinite(oos_sharpe_mean)
        and oos_sharpe_mean >= 0.7
        and oos_n_trades_total >= 30
        and oos_max_dd_worst >= -0.25
    ):
        return Verdict("GREEN", "green_thresholds_met")
    if (
        math.isfinite(oos_sharpe_mean)
        and 0.3 <= oos_sharpe_mean < 0.7
        and oos_n_trades_total >= 15
        and oos_max_dd_worst >= -0.30
    ):
        return Verdict("YELLOW", "yellow_thresholds_met")
    return Verdict("RED", "thresholds_not_met")


def _write_report(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_format_report(result), encoding="utf-8")


def _format_report(result: dict[str, Any]) -> str:
    config: WalkForwardConfig = result["config"]
    data_span = result["data_span"]
    aggregate = result["aggregate"]
    verdict: Verdict = result["verdict"]
    generated = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# Unlock Short V1 \u2014 Walk-Forward Validation",
        "",
        f"_Generated {generated}_",
        "",
        f"## Verdict: {verdict.label}",
        f"Reason: {verdict.reason}",
        "",
        "## Data Span",
        f"- start: {_fmt_date(data_span['start'])}",
        f"- end: {_fmt_date(data_span['end'])}",
        f"- total span: {data_span['total_days']} days",
        f"- n_candidate_events (has_hl_perp): {data_span['n_candidate_events']}",
        "",
        "## Walk-Forward Config",
        f"- n_splits: {config.n_splits}",
        f"- mode: {config.mode}",
        f"- min_train_days: {result['effective_min_train_days']}",
        f"- test_days: {config.test_days}",
        "",
        "## Per-Split Results",
        "",
        "| split | is_start | is_end | oos_start | oos_end | is_best_config | "
        "is_sharpe | is_n_trades | oos_sharpe | oos_n_trades | oos_max_dd | "
        "eligible_in_is | is_selection_mode |",
        "| ---: | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | :---: | --- |",
        *_split_rows(result["split_results"]),
        "",
        "## Aggregate OOS Stats",
        "",
        "| Metric | Value | Threshold | Status |",
        "| --- | --- | --- | --- |",
        *_aggregate_rows(aggregate),
        "",
        "## Decision",
        "",
        _decision_paragraph(verdict, aggregate),
    ]
    return "\n".join(lines) + "\n"


def _split_rows(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["| - | - | - | - | - | - | - | - | - | - | - | - | - |"]

    output = []
    for row in rows:
        output.append(
            f"| {row['split']} | {_fmt_date(row['is_start'])} | {_fmt_date(row['is_end'])} | "
            f"{_fmt_date(row['oos_start'])} | {_fmt_date(row['oos_end'])} | "
            f"{row['is_best_config']} | {_fmt_num(row['is_sharpe'], 2)} | "
            f"{row['is_n_trades']} | "
            f"{_fmt_num_or_na(row['oos_sharpe'], 2, row['oos_n_trades'])} | "
            f"{row['oos_n_trades']} | "
            f"{_fmt_pct_or_na(row['oos_max_dd'], row['oos_n_trades'])} | "
            f"{_fmt_bool(row['eligible_in_is'])} |"
            f" {row['is_selection_mode']} |"
        )
    return output


def _aggregate_rows(aggregate: dict[str, Any]) -> list[str]:
    oos_n_trades_total = int(aggregate["oos_n_trades_total"])
    no_sample = oos_n_trades_total == 0
    oos_sharpe_mean = aggregate["oos_sharpe_mean"]
    oos_sharpe_min = aggregate["oos_sharpe_min"]
    oos_max_dd_worst = aggregate["oos_max_dd_worst"]
    is_oos_decay = aggregate["is_oos_decay"]
    return [
        "| OOS Sharpe (mean) | "
        f"{_fmt_num(oos_sharpe_mean, 2) if not no_sample else 'n/a'} | "
        ">= 0.7 (GREEN) / >= 0.3 (YELLOW) | "
        f"{_no_sample_status(no_sample, _sharpe_status(oos_sharpe_mean))} |",
        "| OOS Sharpe (min/worst) | "
        f"{_fmt_num(oos_sharpe_min, 2) if not no_sample else 'n/a'} | >= 0 desired | "
        f"{_no_sample_status(no_sample, _pass_fail(float(oos_sharpe_min) >= 0))} |",
        "| OOS n_trades (total) | "
        f"{oos_n_trades_total} | >= 30 (GREEN) / >= 15 (YELLOW) | "
        f"{_trades_status(oos_n_trades_total)} |",
        "| OOS Max DD (worst) | "
        f"{_fmt_pct(oos_max_dd_worst) if not no_sample else 'n/a'} | "
        ">= -25% (GREEN) / >= -30% (YELLOW) | "
        f"{_no_sample_status(no_sample, _drawdown_status(oos_max_dd_worst))} |",
        f"| {IS_OOS_DECAY_LABEL} | "
        f"{_fmt_pct(is_oos_decay) if not no_sample else 'n/a'} | "
        f"<= 30% desired | {_no_sample_status(no_sample, _decay_status(is_oos_decay))} |",
    ]


def _decision_paragraph(verdict: Verdict, aggregate: dict[str, Any]) -> str:
    oos_n_trades_total = int(aggregate["oos_n_trades_total"])
    no_sample = oos_n_trades_total == 0
    stats = (
        f"OOS Sharpe mean "
        f"{_fmt_num(aggregate['oos_sharpe_mean'], 2) if not no_sample else 'n/a'}, "
        f"{oos_n_trades_total} OOS trades, worst MaxDD "
        f"{_fmt_pct(aggregate['oos_max_dd_worst']) if not no_sample else 'n/a'}, and "
        f"{IS_OOS_DECAY_LABEL} "
        f"{_fmt_pct(aggregate['is_oos_decay']) if not no_sample else 'n/a'}"
    )
    if verdict.label == "GREEN":
        action = "include it in the paper portfolio candidate set at 10% starting weight."
    elif verdict.label == "YELLOW":
        action = "keep it as a low-weight candidate at 3% starting paper weight."
    else:
        action = "archive the evidence and skip the unlock-short strategy for Phase 2."
    return f"The verdict is {verdict.label} because {verdict.reason}: {stats}. Recommended action: {action}"


def _config_label(row: dict[str, Any]) -> str:
    return f"pre={int(row['pre_window'])} min={float(row['min_pct']):.2f}"


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(sum(float(value) for value in values) / len(values))


def _is_oos_decay(mean_is_sharpe: float, mean_oos_sharpe: float) -> float:
    if not math.isfinite(mean_is_sharpe) or math.isclose(mean_is_sharpe, 0.0):
        return float("nan")
    return float((mean_is_sharpe - mean_oos_sharpe) / mean_is_sharpe)


def _sort_sharpe(row: dict[str, Any]) -> float:
    value = float(row["sharpe"])
    return value if math.isfinite(value) else float("-inf")


def _coerce_bool_series(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.astype("bool")
    return series.astype("string").str.lower().isin({"true", "1", "yes", "y"})


def _fmt_date(value: Any) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _fmt_num(value: Any, decimals: int) -> str:
    number = float(value)
    if not math.isfinite(number):
        return "n/a"
    return f"{number:.{decimals}f}"


def _fmt_num_or_na(value: Any, decimals: int, n_trades: int) -> str:
    if int(n_trades) == 0:
        return "n/a"
    return _fmt_num(value, decimals)


def _fmt_pct(value: Any) -> str:
    number = float(value)
    if not math.isfinite(number):
        return "n/a"
    return f"{number * 100:.2f}%"


def _fmt_pct_or_na(value: Any, n_trades: int) -> str:
    if int(n_trades) == 0:
        return "n/a"
    return _fmt_pct(value)


def _no_sample_status(no_sample: bool, status: str) -> str:
    if no_sample:
        return "NO SAMPLE"
    return status


def _fmt_bool(value: bool) -> str:
    return "yes" if value else "no"


def _pass_fail(condition: bool) -> str:
    return "PASS" if condition else "FAIL"


def _sharpe_status(value: Any) -> str:
    number = float(value)
    if not math.isfinite(number):
        return "FAIL"
    if number >= 0.7:
        return "GREEN"
    if number >= 0.3:
        return "YELLOW"
    return "FAIL"


def _trades_status(value: Any) -> str:
    n_trades = int(value)
    if n_trades >= 30:
        return "GREEN"
    if n_trades >= 15:
        return "YELLOW"
    return "FAIL"


def _drawdown_status(value: Any) -> str:
    number = float(value)
    if number >= -0.25:
        return "GREEN"
    if number >= -0.30:
        return "YELLOW"
    return "FAIL"


def _decay_status(value: Any) -> str:
    number = float(value)
    return _pass_fail(math.isfinite(number) and number <= 0.30)


def _median_int(values: Any) -> int:
    sorted_values = sorted(int(value) for value in values)
    if not sorted_values:
        return 0
    middle = len(sorted_values) // 2
    return int(sorted_values[middle])


def _log(message: str) -> None:
    print(message, file=sys.stderr)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run unlock-short walk-forward validation.")
    parser.add_argument("--n-splits", type=int, default=3)
    parser.add_argument("--mode", choices=["expanding", "rolling"], default="expanding")
    parser.add_argument("--min-train-days", type=int, default=150)
    parser.add_argument("--test-days", type=int, default=60)
    parser.add_argument("--interval", default="1d")
    parser.add_argument("--init-cash", type=float, default=10_000.0)
    parser.add_argument("--fees", type=float, default=0.0005)
    parser.add_argument("--slippage", type=float, default=0.0002)
    parser.add_argument("--report", type=Path, default=Path("reports/unlock_v1_walkforward.md"))
    args = parser.parse_args()
    _validate_args(parser, args)
    return args


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.n_splits < 1:
        parser.error("--n-splits must be at least 1")
    if args.min_train_days < 1:
        parser.error("--min-train-days must be at least 1")
    if args.test_days < 1:
        parser.error("--test-days must be at least 1")
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
    config = WalkForwardConfig(
        n_splits=args.n_splits,
        mode=args.mode,
        min_train_days=args.min_train_days,
        test_days=args.test_days,
        interval=args.interval,
        init_cash=args.init_cash,
        fees=args.fees,
        slippage=args.slippage,
        report=args.report,
    )
    try:
        result = run_walkforward(config)
    except RuntimeError as error:
        _log(f"error: {error}")
        return 1

    verdict: Verdict = result["verdict"]
    print(f"wrote report: {config.report}")
    print(f"verdict: {verdict.label} ({verdict.reason})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
