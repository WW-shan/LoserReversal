from __future__ import annotations

import argparse
import math
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from infra.backtest.walkforward import walk_forward_splits
from infra.pipeline import interval_timedelta
from infra.storage import read_fills, read_wallets
from signals.wallet_cluster_v1 import cluster_signal

if __package__:
    from scripts.run_wallet_cluster_backtest import (
        HOLDING_HOURS_GRID,
        MIN_WALLETS_GRID,
        WINDOW_MINUTES_GRID,
        WalletClusterBacktestConfig,
        backtest_cluster_events,
    )
    from scripts.run_wallet_reverse_backtest import (
        CACHE_ERRORS,
        backtest_freq,
        coerce_utc_timestamp,
        filter_fills_by_end,
        filter_fills_by_start,
    )
else:
    from run_wallet_cluster_backtest import (
        HOLDING_HOURS_GRID,
        MIN_WALLETS_GRID,
        WINDOW_MINUTES_GRID,
        WalletClusterBacktestConfig,
        backtest_cluster_events,
    )
    from run_wallet_reverse_backtest import (
        CACHE_ERRORS,
        backtest_freq,
        coerce_utc_timestamp,
        filter_fills_by_end,
        filter_fills_by_start,
    )


IS_OOS_DECAY_LABEL = "IS->OOS decay"


@dataclass(frozen=True)
class WalkForwardConfig:
    n_splits: int = 3
    mode: str = "expanding"
    min_train_days: int = 120
    test_days: int = 30
    top_wallet_n: int = 50
    candle_interval: str = "1h"
    init_cash: float = 10_000.0
    fees: float = 0.0005
    slippage: float = 0.0002
    report: Path = Path("reports/wallet_reverse_walkforward.md")


@dataclass(frozen=True)
class Verdict:
    label: str
    reason: str


def run_walkforward(config: WalkForwardConfig) -> dict[str, Any]:
    started = time.perf_counter()
    pool_fills, failed_wallets = _load_pool_fills(config.top_wallet_n)
    if not pool_fills:
        raise RuntimeError("no cached wallet fills available")

    start, end, n_fills = _pool_span(pool_fills)
    (
        splits,
        effective_n_splits,
        effective_min_train_days,
        effective_test_days,
    ) = _walk_forward_splits_with_fallback(
        start=start.to_pydatetime(),
        end=end.to_pydatetime(),
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
        split_results.append(_run_split(index, split, pool_fills, config))

    aggregate = _aggregate_split_results(split_results)
    verdict = _verdict(aggregate)
    result = {
        "config": config,
        "effective_n_splits": effective_n_splits,
        "effective_min_train_days": effective_min_train_days,
        "effective_test_days": effective_test_days,
        "data_span": {
            "start": start,
            "end": end,
            "total_days": int((end - start).days),
            "n_fills": int(n_fills),
            "n_wallets_with_fills": len(pool_fills),
            "n_failed_wallets": len(failed_wallets),
        },
        "split_results": split_results,
        "aggregate": aggregate,
        "verdict": verdict,
        "verdict_summary": _decision_paragraph(verdict, aggregate),
        "runtime_seconds": time.perf_counter() - started,
    }
    _write_report(config.report, result)
    return result


def _load_pool_fills(top_wallet_n: int) -> tuple[dict[str, pd.DataFrame], list[str]]:
    wallets = read_wallets().head(top_wallet_n).copy()
    pool_fills: dict[str, pd.DataFrame] = {}
    failed_wallets: list[str] = []
    for row in wallets.itertuples(index=False):
        address = str(row.eth_address).lower()
        try:
            fills = read_fills(address)
        except CACHE_ERRORS as error:
            failed_wallets.append(address)
            _log(f"warning: skipping {address} fills: {error}")
            continue
        if fills.empty:
            continue
        pool_fills[address] = fills
    return pool_fills, failed_wallets


def _pool_span(pool_fills: dict[str, pd.DataFrame]) -> tuple[pd.Timestamp, pd.Timestamp, int]:
    starts = []
    ends = []
    n_fills = 0
    for fills in pool_fills.values():
        fill_times = _fill_times(fills).dropna()
        if fill_times.empty:
            continue
        starts.append(fill_times.min())
        ends.append(fill_times.max())
        n_fills += int(len(fill_times))
    if not starts or not ends:
        raise RuntimeError("no timestamped wallet fills available")
    return min(starts), max(ends), n_fills


def _filter_pool_fills_by_date(
    pool_fills: dict[str, pd.DataFrame],
    date_start: datetime,
    date_end: datetime,
) -> dict[str, pd.DataFrame]:
    filtered = {}
    for address, fills in pool_fills.items():
        window_fills = filter_fills_by_start(fills, date_start)
        window_fills = filter_fills_by_end(window_fills, date_end)
        if not window_fills.empty:
            filtered[address] = window_fills
    return filtered


def _fill_times(fills: pd.DataFrame) -> pd.Series:
    if "time" in fills.columns:
        values = fills["time"]
    else:
        values = fills.index
    return pd.Series(pd.to_datetime(values, utc=True, errors="coerce"), index=fills.index)


def _walk_forward_splits_with_fallback(
    *,
    start: datetime,
    end: datetime,
    n_splits: int,
    mode: str,
    min_train_days: int,
    test_days: int,
) -> tuple[list[tuple[tuple[datetime, datetime], tuple[datetime, datetime]]], int, int, int]:
    min_train_candidates = list(range(min_train_days, 29, -15))
    test_day_candidates = list(range(test_days, 4, -5))
    split_candidates = list(range(n_splits, 0, -1))
    last_error: ValueError | None = None

    for candidate_splits in split_candidates:
        for candidate_test_days in test_day_candidates:
            for candidate_min_train_days in min_train_candidates:
                try:
                    splits = walk_forward_splits(
                        start,
                        end,
                        n_splits=candidate_splits,
                        mode=mode,
                        min_train_days=candidate_min_train_days,
                        test_days=candidate_test_days,
                    )
                except ValueError as error:
                    last_error = error
                    continue
                if (
                    candidate_splits < n_splits
                    or candidate_min_train_days < min_train_days
                    or candidate_test_days < test_days
                ):
                    _log(
                        "[WARN] walk-forward fallback: requested "
                        f"(n_splits={n_splits}, min_train_days={min_train_days}, "
                        f"test_days={test_days}); using "
                        f"(n_splits={candidate_splits}, "
                        f"min_train_days={candidate_min_train_days}, "
                        f"test_days={candidate_test_days})"
                    )
                return (
                    splits,
                    candidate_splits,
                    candidate_min_train_days,
                    candidate_test_days,
                )

    detail = f": {last_error}" if last_error is not None else ""
    raise RuntimeError(f"walk-forward split infeasible for available data span{detail}")


def _run_split(
    split_index: int,
    split: tuple[tuple[datetime, datetime], tuple[datetime, datetime]],
    pool_fills: dict[str, pd.DataFrame],
    config: WalkForwardConfig,
) -> dict[str, Any]:
    (train_start, train_end), (test_start, test_end) = split
    train_pool = _filter_pool_fills_by_date(pool_fills, train_start, train_end)
    rows = _run_grid(train_pool, train_start, train_end, config)
    best_row, eligible_in_is, selection_mode = _select_best_is_row(rows, split_index)

    test_pool = _filter_pool_fills_by_date(pool_fills, test_start, test_end)
    oos_config = _cluster_config_from_row(best_row, config, test_start, test_end)
    oos_result = _run_cluster_backtest_for_pool(test_pool, oos_config)
    oos_stats = oos_result["portfolio_stats"]

    return {
        "split": split_index,
        "is_start": train_start,
        "is_end": train_end,
        "oos_start": test_start,
        "oos_end": test_end,
        "is_best_config": _config_label(best_row),
        "is_min_wallets": int(best_row["min_wallets"]),
        "is_window_minutes": int(best_row["window_minutes"]),
        "is_holding_hours": float(best_row["holding_hours"]),
        "is_ir": float(best_row["trade_level_ir"]),
        "is_daily_sharpe": float(best_row["daily_sharpe"]),
        "is_max_dd": float(best_row["max_dd"]),
        "is_n_trades": int(best_row["n_trades"]),
        "oos_ir": float(oos_stats["trade_level_ir"]),
        "oos_daily_sharpe": float(oos_stats["daily_sharpe"]),
        "oos_max_dd": float(oos_stats["max_dd"]),
        "oos_n_trades": int(oos_stats["n_trades"]),
        "eligible_in_is": eligible_in_is,
        "is_selection_mode": selection_mode,
    }


def _run_grid(
    pool_fills: dict[str, pd.DataFrame],
    date_start: datetime,
    date_end: datetime,
    config: WalkForwardConfig,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    total = len(MIN_WALLETS_GRID) * len(WINDOW_MINUTES_GRID) * len(HOLDING_HOURS_GRID)
    combo_index = 0
    for min_wallets in MIN_WALLETS_GRID:
        for window_minutes in WINDOW_MINUTES_GRID:
            for holding_hours in HOLDING_HOURS_GRID:
                combo_index += 1
                cluster_config = WalletClusterBacktestConfig(
                    min_wallets=min_wallets,
                    window_minutes=window_minutes,
                    holding_hours=holding_hours,
                    top_wallet_n=config.top_wallet_n,
                    candle_interval=config.candle_interval,
                    init_cash=config.init_cash,
                    fees=config.fees,
                    slippage=config.slippage,
                    date_start=date_start,
                    date_end=date_end,
                    report=None,
                )
                result = _run_cluster_backtest_for_pool(pool_fills, cluster_config)
                stats = result["portfolio_stats"]
                row = {
                    "min_wallets": min_wallets,
                    "window_minutes": window_minutes,
                    "holding_hours": holding_hours,
                    "trade_level_ir": float(stats["trade_level_ir"]),
                    "daily_sharpe": float(stats["daily_sharpe"]),
                    "max_dd": float(stats["max_dd"]),
                    "n_trades": int(stats["n_trades"]),
                }
                rows.append(row)
                _log(
                    f"  [{combo_index}/{total}] N={min_wallets} W={window_minutes} "
                    f"H={holding_hours:g} trades={row['n_trades']} "
                    f"IR={row['trade_level_ir']:.2f}"
                )
    return rows


def _run_cluster_backtest_for_pool(
    pool_fills: dict[str, pd.DataFrame],
    config: WalletClusterBacktestConfig,
) -> dict[str, Any]:
    freq = backtest_freq(config.candle_interval)
    events_by_coin = cluster_signal(
        pool_fills,
        min_wallets=config.min_wallets,
        window_minutes=config.window_minutes,
        holding_hours=config.holding_hours,
    )
    return backtest_cluster_events(events_by_coin, config, freq)


def _cluster_config_from_row(
    row: dict[str, Any],
    config: WalkForwardConfig,
    date_start: datetime,
    date_end: datetime,
) -> WalletClusterBacktestConfig:
    return WalletClusterBacktestConfig(
        min_wallets=int(row["min_wallets"]),
        window_minutes=int(row["window_minutes"]),
        holding_hours=float(row["holding_hours"]),
        top_wallet_n=config.top_wallet_n,
        candle_interval=config.candle_interval,
        init_cash=config.init_cash,
        fees=config.fees,
        slippage=config.slippage,
        date_start=date_start,
        date_end=date_end,
        report=None,
    )


def _select_best_is_row(
    rows: list[dict[str, Any]],
    split_index: int | None = None,
) -> tuple[dict[str, Any], bool, str]:
    if not rows:
        raise RuntimeError("parameter sweep returned no rows")

    eligible_rows = [row for row in rows if int(row["n_trades"]) >= 100]
    if eligible_rows:
        return max(eligible_rows, key=_sort_ir), True, "eligible"

    positive_trade_rows = [row for row in rows if int(row["n_trades"]) > 0]
    if positive_trade_rows:
        median_n_trades = _median_int(int(row["n_trades"]) for row in positive_trade_rows)
        median_bucket_rows = [
            row
            for row in positive_trade_rows
            if int(row["n_trades"]) >= median_n_trades and float(row["trade_level_ir"]) > 0
        ]
        if median_bucket_rows:
            return max(median_bucket_rows, key=_sort_ir), False, "positive_trades_median"
        return max(positive_trade_rows, key=_sort_ir), False, "positive_trades_any"

    if split_index is not None:
        _log(
            f"[WARN] split {split_index}: no positive-trade IS config; "
            "fallback chose 0-trade max-IR"
        )
    return max(rows, key=_sort_ir), False, "zero_trade_fallback"


def _aggregate_split_results(rows: list[dict[str, Any]]) -> dict[str, Any]:
    mean_is_ir = _mean([row["is_ir"] for row in rows])
    mean_oos_ir = _mean([row["oos_ir"] for row in rows])
    oos_max_dd_values = [float(row["oos_max_dd"]) for row in rows]
    return {
        "mean_is_ir": mean_is_ir,
        "oos_ir_mean": mean_oos_ir,
        "oos_ir_min": min(float(row["oos_ir"]) for row in rows) if rows else 0.0,
        "oos_max_dd_worst": min(oos_max_dd_values) if oos_max_dd_values else 0.0,
        "oos_n_trades_total": sum(int(row["oos_n_trades"]) for row in rows),
        "is_oos_decay": _is_oos_decay(mean_is_ir, mean_oos_ir),
    }


def _verdict(aggregate: dict[str, Any]) -> Verdict:
    """
    Determine verdict label and reason from aggregate stats.

    RED reason order (first match wins):
    - data_gap: oos_n_trades_total == 0
    - insufficient_sample: 0 < oos_n_trades_total < 50
    - max_drawdown_breach: oos_n_trades_total >= 50 AND oos_max_dd_worst < -0.25
    - oos_ir_below_yellow: oos_n_trades_total >= 50, dd ok, but oos_ir_mean < 1.0
    - insufficient_oos_trades: 50 <= oos_n_trades_total < 100, ir >= 1.0, dd ok

    YELLOW: oos_n_trades_total >= 100 AND 1.0 <= oos_ir_mean < 1.2 AND dd >= -0.25 (yellow_thresholds_met)
    GREEN: oos_n_trades_total >= 100 AND oos_ir_mean >= 1.2 AND dd >= -0.25 (green_thresholds_met)

    Note: thresholds_not_met is NOT emitted by this function (only by unlock_walkforward).
    """
    oos_ir_mean = float(aggregate["oos_ir_mean"])
    oos_n_trades_total = int(aggregate["oos_n_trades_total"])
    oos_max_dd_worst = float(aggregate["oos_max_dd_worst"])

    if oos_n_trades_total == 0:
        return Verdict("RED", "data_gap")
    if oos_n_trades_total < 50:
        return Verdict("RED", "insufficient_sample")
    if oos_max_dd_worst < -0.25:
        return Verdict("RED", "max_drawdown_breach")
    if not math.isfinite(oos_ir_mean) or oos_ir_mean < 1.0:
        return Verdict("RED", "oos_ir_below_yellow")
    if oos_n_trades_total < 100:
        return Verdict("RED", "insufficient_oos_trades")
    if oos_ir_mean >= 1.2:
        return Verdict("GREEN", "green_thresholds_met")
    return Verdict("YELLOW", "yellow_thresholds_met")


def _write_report(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_format_report(result), encoding="utf-8")


def _format_report(result: dict[str, Any]) -> str:
    config: WalkForwardConfig = result["config"]
    data_span = result["data_span"]
    aggregate = result["aggregate"]
    verdict: Verdict = result["verdict"]
    generated = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    fallback_used = _walk_forward_fallback_used(config, result)

    lines = [
        "# Wallet Cluster Reverse V1 - Walk-Forward Validation",
        "",
        f"_Generated {generated}_",
        "",
        f"## Verdict: {verdict.label}",
        *(["> [WARN] walk-forward fallback used"] if fallback_used else []),
        f"Reason: {verdict.reason}",
        "",
        "## Data Span",
        f"- start: {_fmt_date(data_span['start'])}",
        f"- end: {_fmt_date(data_span['end'])}",
        f"- total span: {data_span['total_days']} days",
        f"- n_fills: {data_span['n_fills']}",
        f"- n_wallets_with_fills: {data_span['n_wallets_with_fills']}",
        f"- n_failed_wallets: {data_span['n_failed_wallets']}",
        "",
        "## Walk-Forward Config",
        f"- n_splits: {config.n_splits} (effective: {result['effective_n_splits']})",
        f"- mode: {config.mode}",
        f"- min_train_days: {config.min_train_days} "
        f"(effective: {result['effective_min_train_days']})",
        f"- test_days: {config.test_days} (effective: {result['effective_test_days']})",
        f"- top_wallet_n: {config.top_wallet_n}",
        f"- grid: {len(MIN_WALLETS_GRID) * len(WINDOW_MINUTES_GRID) * len(HOLDING_HOURS_GRID)} configs",
        "",
        "## Per-Split Results",
        "",
        "| split | is_start | is_end | oos_start | oos_end | is_best_config | "
        "is_ir | is_n_trades | oos_ir | oos_daily_sharpe | oos_n_trades | "
        "oos_max_dd | eligible_in_is | is_selection_mode |",
        "| ---: | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | "
        "---: | :---: | --- |",
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


def _walk_forward_fallback_used(config: WalkForwardConfig, result: dict[str, Any]) -> bool:
    return (
        int(result["effective_n_splits"]) < config.n_splits
        or int(result["effective_min_train_days"]) < config.min_train_days
        or int(result["effective_test_days"]) < config.test_days
    )


def _split_rows(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["| - | - | - | - | - | - | - | - | - | - | - | - | - | - |"]

    output = []
    for row in rows:
        output.append(
            f"| {row['split']} | {_fmt_date(row['is_start'])} | {_fmt_date(row['is_end'])} | "
            f"{_fmt_date(row['oos_start'])} | {_fmt_date(row['oos_end'])} | "
            f"{row['is_best_config']} | {_fmt_num(row['is_ir'], 2)} | "
            f"{row['is_n_trades']} | {_fmt_num_or_na(row['oos_ir'], 2, row['oos_n_trades'])} | "
            f"{_fmt_num_or_na(row['oos_daily_sharpe'], 2, row['oos_n_trades'])} | "
            f"{row['oos_n_trades']} | {_fmt_pct_or_na(row['oos_max_dd'], row['oos_n_trades'])} | "
            f"{_fmt_bool(row['eligible_in_is'])} | {row['is_selection_mode']} |"
        )
    return output


def _aggregate_rows(aggregate: dict[str, Any]) -> list[str]:
    oos_n_trades_total = int(aggregate["oos_n_trades_total"])
    no_sample = oos_n_trades_total == 0
    oos_ir_mean = aggregate["oos_ir_mean"]
    oos_ir_min = aggregate["oos_ir_min"]
    oos_max_dd_worst = aggregate["oos_max_dd_worst"]
    is_oos_decay = aggregate["is_oos_decay"]
    return [
        "| OOS Trade-level IR (mean) | "
        f"{_fmt_num(oos_ir_mean, 2) if not no_sample else 'n/a'} | "
        ">= 1.2 (GREEN) / >= 1.0 (YELLOW) | "
        f"{_no_sample_status(no_sample, _ir_status(oos_ir_mean))} |",
        "| OOS Trade-level IR (min/worst) | "
        f"{_fmt_num(oos_ir_min, 2) if not no_sample else 'n/a'} | >= 0 desired | "
        f"{_no_sample_status(no_sample, _pass_fail(float(oos_ir_min) >= 0))} |",
        "| OOS n_trades (total) | "
        f"{oos_n_trades_total} | >= 100 | {_trades_status(oos_n_trades_total)} |",
        "| OOS Max DD (worst) | "
        f"{_fmt_pct(oos_max_dd_worst) if not no_sample else 'n/a'} | >= -25% | "
        f"{_no_sample_status(no_sample, _drawdown_status(oos_max_dd_worst))} |",
        f"| {IS_OOS_DECAY_LABEL} | "
        f"{_fmt_pct(is_oos_decay) if not no_sample else 'n/a'} | "
        f"<= 30% desired | {_no_sample_status(no_sample, _decay_status(is_oos_decay))} |",
    ]


def _decision_paragraph(verdict: Verdict, aggregate: dict[str, Any]) -> str:
    oos_n_trades_total = int(aggregate["oos_n_trades_total"])
    no_sample = oos_n_trades_total == 0
    stats = (
        f"OOS trade-level IR mean "
        f"{_fmt_num(aggregate['oos_ir_mean'], 2) if not no_sample else 'n/a'}, "
        f"{oos_n_trades_total} OOS trades, worst MaxDD "
        f"{_fmt_pct(aggregate['oos_max_dd_worst']) if not no_sample else 'n/a'}, and "
        f"{IS_OOS_DECAY_LABEL} "
        f"{_fmt_pct(aggregate['is_oos_decay']) if not no_sample else 'n/a'}"
    )
    if verdict.label == "GREEN":
        action = "include the wallet-reverse line as a paper portfolio candidate."
    elif verdict.label == "YELLOW":
        action = "keep the cluster signal only as a low-weight paper candidate."
    else:
        action = "kill the wallet-reverse line and skip Phase 4 sybil clustering."
    return f"The verdict is {verdict.label} because {verdict.reason}: {stats}. Action: {action}"


def _config_label(row: dict[str, Any]) -> str:
    return (
        f"N={int(row['min_wallets'])} W={int(row['window_minutes'])}m "
        f"H={float(row['holding_hours']):g}h"
    )


def _sort_ir(row: dict[str, Any]) -> float:
    value = float(row["trade_level_ir"])
    return value if math.isfinite(value) else float("-inf")


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(sum(float(value) for value in values) / len(values))


def _is_oos_decay(mean_is_ir: float, mean_oos_ir: float) -> float:
    if not math.isfinite(mean_is_ir) or math.isclose(mean_is_ir, 0.0):
        return float("nan")
    return float((mean_is_ir - mean_oos_ir) / mean_is_ir)


def _median_int(values: Any) -> int:
    sorted_values = sorted(int(value) for value in values)
    if not sorted_values:
        return 0
    middle = len(sorted_values) // 2
    return int(sorted_values[middle])


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


def _fmt_bool(value: bool) -> str:
    return "yes" if value else "no"


def _no_sample_status(no_sample: bool, status: str) -> str:
    if no_sample:
        return "NO SAMPLE"
    return status


def _pass_fail(condition: bool) -> str:
    return "PASS" if condition else "FAIL"


def _ir_status(value: Any) -> str:
    number = float(value)
    if not math.isfinite(number):
        return "FAIL"
    if number >= 1.2:
        return "GREEN"
    if number >= 1.0:
        return "YELLOW"
    return "FAIL"


def _trades_status(value: Any) -> str:
    return _pass_fail(int(value) >= 100)


def _drawdown_status(value: Any) -> str:
    return _pass_fail(float(value) >= -0.25)


def _decay_status(value: Any) -> str:
    number = float(value)
    return _pass_fail(math.isfinite(number) and number <= 0.30)


def _parse_datetime_arg(value: str) -> datetime:
    try:
        return coerce_utc_timestamp(value).to_pydatetime()
    except (TypeError, ValueError) as error:
        raise argparse.ArgumentTypeError(f"invalid datetime {value!r}") from error


def _log(message: str) -> None:
    print(message, file=sys.stderr)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run wallet cluster walk-forward validation.")
    parser.add_argument("--n-splits", type=int, default=3)
    parser.add_argument("--mode", choices=["expanding", "rolling"], default="expanding")
    parser.add_argument("--min-train-days", type=int, default=120)
    parser.add_argument("--test-days", type=int, default=30)
    parser.add_argument("--top-wallet-n", type=int, default=50)
    parser.add_argument("--candle-interval", default="1h")
    parser.add_argument("--init-cash", type=float, default=10_000.0)
    parser.add_argument("--fees", type=float, default=0.0005)
    parser.add_argument("--slippage", type=float, default=0.0002)
    parser.add_argument("--report", type=Path, default=Path("reports/wallet_reverse_walkforward.md"))
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
    config = WalkForwardConfig(
        n_splits=args.n_splits,
        mode=args.mode,
        min_train_days=args.min_train_days,
        test_days=args.test_days,
        top_wallet_n=args.top_wallet_n,
        candle_interval=args.candle_interval,
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
