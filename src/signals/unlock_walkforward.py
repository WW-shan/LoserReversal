from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from signals.unlock_grid import GridCell, iter_grid, run_cell


DEFAULT_INIT_CASH = 10_000.0
DEFAULT_FEES = 0.0005
DEFAULT_SLIPPAGE = 0.0002
DEFAULT_GRID_PATH = Path("data/parquet/unlock_grid_v15.parquet")


def select_best_config(
    grid_df: pd.DataFrame,
    signal_code: str,
    train_events: pd.DataFrame,
    train_prices: dict[str, pd.Series],
    train_coverage: pd.DataFrame,
    min_n_trades: int = 15,
    *,
    init_cash: float = DEFAULT_INIT_CASH,
    fees: float = DEFAULT_FEES,
    slippage: float = DEFAULT_SLIPPAGE,
) -> GridCell | None:
    best_cell: GridCell | None = None
    best_sharpe = float("-inf")

    for cell in _candidate_cells(grid_df, signal_code):
        row = run_cell(
            train_events,
            train_prices,
            train_coverage,
            cell,
            init_cash=init_cash,
            fees=fees,
            slippage=slippage,
        )
        n_trades = int(row["n_trades"])
        sharpe = _finite_sharpe(row["sharpe"])
        if n_trades >= min_n_trades and sharpe > best_sharpe:
            best_cell = cell
            best_sharpe = sharpe

    return best_cell


def run_per_signal_walkforward(
    events: pd.DataFrame,
    prices: dict[str, pd.Series],
    coverage: pd.DataFrame,
    splits: Sequence[tuple[tuple[pd.Timestamp, pd.Timestamp], tuple[pd.Timestamp, pd.Timestamp]]],
    signals_to_run: Sequence[str],
    *,
    grid_df: pd.DataFrame | None = None,
    min_n_trades: int = 15,
    init_cash: float = DEFAULT_INIT_CASH,
    fees: float = DEFAULT_FEES,
    slippage: float = DEFAULT_SLIPPAGE,
    fallback_used: bool = False,
) -> pd.DataFrame:
    grid = _grid_frame(grid_df)
    rows: list[dict[str, Any]] = []

    for split_idx, ((train_start, train_end), (test_start, test_end)) in enumerate(splits):
        train_window_start = _utc_timestamp(train_start)
        train_window_end = _utc_timestamp(train_end)
        test_window_start = _utc_timestamp(test_start)
        test_window_end = _utc_timestamp(test_end)
        train_events = _filter_events_by_window(events, train_window_start, train_window_end)
        test_events = _filter_events_by_window(events, test_window_start, test_window_end)
        train_coverage = _filter_coverage_by_window(
            coverage,
            train_window_start,
            train_window_end,
        )
        test_coverage = _filter_coverage_by_window(coverage, test_window_start, test_window_end)

        for signal_code in signals_to_run:
            selected = select_best_config(
                grid,
                signal_code,
                train_events,
                prices,
                train_coverage,
                min_n_trades=min_n_trades,
                init_cash=init_cash,
                fees=fees,
                slippage=slippage,
            )
            stats = _empty_stats(signal_code) if selected is None else run_cell(
                test_events,
                prices,
                test_coverage,
                selected,
                init_cash=init_cash,
                fees=fees,
                slippage=slippage,
            )
            rows.append(
                _walkforward_row(
                    kind="per_signal",
                    signal=signal_code,
                    split_idx=split_idx,
                    train_start=train_window_start,
                    train_end=train_window_end,
                    test_start=test_window_start,
                    test_end=test_window_end,
                    selected=selected,
                    stats=stats,
                    fallback_used=fallback_used,
                )
            )

    rows.extend(_aggregate_rows(rows, kind="per_signal"))
    return pd.DataFrame(rows)


def _candidate_cells(grid_df: pd.DataFrame, signal_code: str) -> list[GridCell]:
    lookup = {
        (cell.code, float(cell.min_unlock_pct), cell.cohort_name): cell for cell in iter_grid()
    }
    if grid_df.empty:
        return [cell for cell in lookup.values() if cell.code == signal_code]

    cells: list[GridCell] = []
    seen: set[tuple[str, float, str]] = set()
    for row in grid_df.to_dict("records"):
        code = str(row.get("signal", ""))
        min_unlock_pct = _row_min_unlock_pct(row)
        cohort = str(row.get("cohort", ""))
        key = (code, min_unlock_pct, cohort)
        cell = lookup.get(key)
        if code == signal_code and cell is not None and key not in seen:
            cells.append(cell)
            seen.add(key)
    return cells


def _grid_frame(grid_df: pd.DataFrame | None) -> pd.DataFrame:
    if grid_df is not None:
        return grid_df
    if DEFAULT_GRID_PATH.exists():
        return pd.read_parquet(DEFAULT_GRID_PATH)
    return pd.DataFrame()


def _filter_events_by_window(
    events: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    if events.empty or "unlock_date" not in events.columns:
        return events.iloc[0:0].copy()

    frame = events.copy()
    frame["unlock_date"] = pd.to_datetime(frame["unlock_date"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["unlock_date"])
    mask = (frame["unlock_date"] >= start) & (frame["unlock_date"] < end)
    return frame.loc[mask].reset_index(drop=True)


def _filter_coverage_by_window(
    coverage: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    if coverage.empty or "unlock_date" not in coverage.columns:
        return coverage.copy()

    frame = coverage.copy()
    frame["unlock_date"] = pd.to_datetime(frame["unlock_date"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["unlock_date"])
    mask = (frame["unlock_date"] >= start) & (frame["unlock_date"] < end)
    return frame.loc[mask].reset_index(drop=True)


def _walkforward_row(
    *,
    kind: str,
    signal: str,
    split_idx: int,
    train_start: pd.Timestamp | pd.NaT,
    train_end: pd.Timestamp | pd.NaT,
    test_start: pd.Timestamp | pd.NaT,
    test_end: pd.Timestamp | pd.NaT,
    selected: GridCell | None,
    stats: dict[str, Any],
    fallback_used: bool,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "signal": signal,
        "split_idx": split_idx,
        "train_start": train_start,
        "train_end": train_end,
        "test_start": test_start,
        "test_end": test_end,
        "selected_min_pct": (
            float(selected.min_unlock_pct) if selected is not None else float("nan")
        ),
        "selected_cohort": selected.cohort_name if selected is not None else "",
        "n_trades": int(stats["n_trades"]),
        "sharpe": float(stats["sharpe"]),
        "sortino": float(stats["sortino"]),
        "win_rate": float(stats["win_rate"]),
        "max_dd": float(stats["max_dd"]),
        "total_return": float(stats["total_return"]),
        "fallback_used": bool(fallback_used),
    }


def _empty_stats(signal_code: str) -> dict[str, Any]:
    return {
        "signal": signal_code,
        "min_unlock_pct": float("nan"),
        "cohort": "",
        "n_trades": 0,
        "win_rate": 0.0,
        "sharpe": 0.0,
        "sortino": 0.0,
        "max_dd": 0.0,
        "total_return": 0.0,
        "mean_pnl": 0.0,
        "median_pnl": 0.0,
    }


def _aggregate_rows(rows: list[dict[str, Any]], *, kind: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    frame = pd.DataFrame(row for row in rows if row["kind"] == kind and row["split_idx"] >= 0)
    if frame.empty:
        return output

    for signal, signal_frame in frame.groupby("signal", sort=False):
        n_trades = int(signal_frame["n_trades"].sum())
        trades_won = (signal_frame["win_rate"] * signal_frame["n_trades"]).sum()
        returns = signal_frame["total_return"].astype("float64")
        output.append(
            {
                "kind": kind,
                "signal": str(signal),
                "split_idx": -1,
                "train_start": pd.NaT,
                "train_end": pd.NaT,
                "test_start": pd.NaT,
                "test_end": pd.NaT,
                "selected_min_pct": float("nan"),
                "selected_cohort": "aggregate",
                "n_trades": n_trades,
                "sharpe": float(signal_frame["sharpe"].mean()),
                "sortino": float(signal_frame["sortino"].mean()),
                "win_rate": float(trades_won / n_trades) if n_trades else 0.0,
                "max_dd": float(signal_frame["max_dd"].min()),
                "total_return": float((1.0 + returns).prod() - 1.0),
                "fallback_used": bool(signal_frame["fallback_used"].any()),
            }
        )
    return output


def _utc_timestamp(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tz is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _row_min_unlock_pct(row: dict[str, Any]) -> float:
    if "min_unlock_pct" in row:
        return float(row["min_unlock_pct"])
    return float(row["min_pct"])


def _finite_sharpe(value: Any) -> float:
    sharpe = float(value)
    if math.isfinite(sharpe):
        return sharpe
    return float("-inf")
